"""Service contracts, transactional transitions and independently authored outcomes."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reviewpoint import models as m
from reviewpoint.app import create_app
from reviewpoint.evaluation import evaluate
from reviewpoint.identity import Principal, ServiceError
from reviewpoint.openai_transport import ProviderResponse
from reviewpoint.storage import Store
from tests.fixtures import DOMAINS, load, profile, seed, submission


@pytest.fixture
def service_demo(tmp_path):
    path = tmp_path / "workspace"
    seed(path)
    service, identity = load(path)
    tokens = json.loads((path / "demo-credentials.json").read_text())
    profiles = json.loads((path / "demo-profiles.json").read_text())
    with TestClient(create_app(service, identity, worker=False)) as client:
        yield Harness(path, service, identity, tokens, profiles, client)


class Harness:
    def __init__(self, path, service, identity, tokens, profiles, client):
        self.path, self.service, self.identity, self.tokens, self.profiles, self.client = (
            path,
            service,
            identity,
            tokens,
            profiles,
            client,
        )
        self.sequence = 0

    def call(self, method, path, who="owner", body=None, key=None):
        self.sequence += 1
        return self.client.request(
            method,
            "/api/v1/projects/" + path,
            json=body,
            headers={
                "Authorization": "Bearer " + self.tokens[who],
                "Idempotency-Key": key or str(self.sequence),
            },
        )

    def start(self, domain="work", supported=True, external_id=None):
        body = submission(domain, supported, external_id=external_id).model_dump(mode="json")
        response = self.call("POST", domain + "/submissions", domain + "-host", body)
        assert response.status_code == 201, response.text
        sub = response.json()
        path = domain + "/cases/" + sub["case_id"]
        response = self.call(
            "POST",
            path + "/assessments",
            domain + "-host",
            {
                "submission_id": sub["submission_id"],
                "profile_ref": {"id": self.profiles[domain], "version": 1},
                "expected_review_token": sub["review_token"],
            },
        )
        assert response.status_code == 202, response.text
        return path, body, sub, response.json()

    def ready(self, domain="work", supported=True, external_id=None):
        path, body, sub, assessment = self.start(domain, supported, external_id)
        assert self.service.process_one()
        current = self.call("GET", path + "/review").json()
        assert current["evaluation_status"] == "completed", current
        return path, body, sub, current

    def decide(self, path, current, answer="yes", who="approver", **extra):
        return self.call(
            "POST",
            path + "/decisions",
            who,
            {
                "assessment_id": current["assessment_id"],
                "expected_review_token": current["review_token"],
                "answer": answer,
                "rationale": "Independent synthetic test judgment",
                "supersedes_decision_id": (current["current_decision"] or {}).get("decision_id"),
                **extra,
            },
        )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("supported,expected", [(True, "yes"), (False, "no")])
def test_all_domains_compute_outcomes_and_persist(service_demo, domain, supported, expected):
    h = service_demo
    path, body, sub, current = h.ready(domain, supported)
    assert current["recommendation"]["answer"] == expected
    assert h.decide(path, current, expected).status_code == 201
    assert h.call("GET", path + "/review").json()["state"] == (
        "approved" if supported else "declined"
    )
    restarted, _ = load(h.path)
    assert restarted.store.verify()["decisions"] == 1
    with restarted.store.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM events WHERE event_type=?", ("decision.recorded",)
            ).fetchone()[0]
            == 1
        )


def test_request_retry_conflict_and_natural_revision(service_demo):
    h = service_demo
    body = submission("work").model_dump(mode="json")
    first = h.call("POST", "work/submissions", "work-host", body, "same")
    assert first.status_code == 201
    assert h.call("POST", "work/submissions", "work-host", body, "same").json() == first.json()
    assert h.call("POST", "work/submissions", "work-host", body, "other-key").json() == first.json()
    body["summary"] = "different"
    assert h.call("POST", "work/submissions", "work-host", body, "same").status_code == 409
    assert h.call("POST", "work/submissions", "work-host", body, "other-body").status_code == 409
    assert h.service.store.verify()["submissions"] == 1


def test_new_revision_and_pending_reassessment_never_fall_back(service_demo):
    h = service_demo
    path, body, sub, current = h.ready()
    decision = h.decide(path, current).json()
    current = h.call("GET", path + "/review").json()
    request = {
        "submission_id": sub["submission_id"],
        "profile_ref": {"id": h.profiles["work"], "version": 1},
        "expected_review_token": current["review_token"],
    }
    for actor in ("approver", "work-host"):
        assert h.call("POST", path + "/assessments", actor, request).status_code == 403
    assert h.call("POST", path + "/assessments", "owner", request).status_code == 202
    pending = h.call("GET", path + "/review").json()
    assert pending["state"] == "evaluating" and pending["current_decision"] is None
    assert h.decide(path, pending, "no").status_code == 409
    assert h.service.recover() == 1
    failed = h.call("GET", path + "/review").json()
    assert (
        failed["state"] == "evaluation_failed"
        and failed["recommendation"] is None
        and failed["current_decision"] is None
    )
    body.update(expected_submission_id=sub["submission_id"], host_revision="revision-2")
    body["work"]["supported"] = 3
    assert h.call("POST", "work/submissions", "work-host", body).status_code == 201
    revised = h.call("GET", path + "/review").json()
    assert revised["state"] == "awaiting_evaluation" and revised["current_decision"] is None
    assert h.call("GET", path + "/decisions/" + decision["decision_id"]).status_code == 200


def test_revocation_restore_and_permission_changes(service_demo):
    h = service_demo
    path, _, _, current = h.ready()
    old = h.decide(path, current).json()
    current = h.call("GET", path + "/review").json()
    revoke = {
        "expected_review_token": current["review_token"],
        "rationale": "Withdraw after independent concern",
    }
    route = path + "/decisions/" + old["decision_id"] + "/revocations"
    assert h.call("POST", route, "approver", revoke).status_code == 403
    result = h.call("POST", route, "owner", revoke, "withdraw")
    assert result.status_code == 201
    assert h.call("POST", route, "owner", revoke, "withdraw").json() == result.json()
    revoked = h.call("GET", path + "/review").json()
    assert revoked["state"] == "revoked" and revoked["current_decision"]["answer"] is None
    assert h.decide(path, revoked, "yes").status_code == 403
    assert h.decide(path, revoked, "yes", "owner").status_code == 201
    member = h.call("GET", "work/memberships").json()["items"]
    approver = next(m for m in member if m["role"] == "approver")
    assert (
        h.call(
            "PUT",
            "work/memberships",
            "owner",
            {
                "actor_id": approver["actor_id"],
                "role": "approver",
                "active": False,
                "expected_version": 1,
                "reason": "Disable access",
            },
        ).status_code
        == 200
    )
    assert h.call("GET", path + "/review", "approver").status_code == 404
    assert h.call("GET", path + "/review").json()["state"] == "approved"
    owner = next(m for m in member if m["role"] == "owner")
    assert (
        h.call(
            "PUT",
            "work/memberships",
            "owner",
            {
                "actor_id": owner["actor_id"],
                "role": "reviewer",
                "active": True,
                "expected_version": 1,
                "reason": "Last owner change",
            },
        ).status_code
        == 409
    )


def test_late_completion_and_concurrent_decision(service_demo):
    h = service_demo
    path, _, sub, first = h.start()
    current = h.call("GET", path + "/review").json()
    second = h.call(
        "POST",
        path + "/assessments",
        "owner",
        {
            "submission_id": sub["submission_id"],
            "profile_ref": {"id": h.profiles["work"], "version": 1},
            "expected_review_token": current["review_token"],
        },
    ).json()
    h.service.process_one()
    assert h.call("GET", path + "/review").json()["assessment_id"] == second["assessment_id"]
    assert h.call("GET", path + "/review").json()["state"] == "evaluating"
    h.service.process_one()
    current = h.call("GET", path + "/review").json()
    principal = h.identity.authenticate(h.tokens["approver"])
    body = m.DecisionRequest(
        assessment_id=current["assessment_id"],
        expected_review_token=current["review_token"],
        answer="yes",
        rationale="Concurrency test",
    )

    def decide(key):
        try:
            return h.service.decide(principal, "work", sub["case_id"], key, body)[0]
        except ServiceError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, ["a", "b"])) == [201, 409]
    assert h.service.store.verify()["decisions"] == 1


@pytest.mark.parametrize(
    "path", ["work", "work/profiles", "work/memberships", "work/cases", "work/events"]
)
def test_no_unauthenticated_reads(service_demo, path):
    assert service_demo.client.get("/api/v1/projects/" + path).status_code == 401


def test_project_and_host_scope_and_spoofed_identity(service_demo):
    h = service_demo
    path, body, sub, current = h.ready()
    for suffix in (
        "review",
        "submissions",
        "assessments",
        "submissions/" + sub["submission_id"],
        "assessments/" + current["assessment_id"],
    ):
        assert h.call("GET", path + "/" + suffix, "reconciliation-host").status_code == 404
        assert (
            h.call("GET", path.replace("work/", "reconciliation/") + "/" + suffix).status_code
            == 404
        )
    assert h.call("POST", "reconciliation/submissions", "work-host", body).status_code == 404
    assert h.decide(path, current, who="reviewer").status_code == 403
    assert h.decide(path, current, who="work-host").status_code == 403
    assert h.decide(path, current, actor_id=Principal("fake", "owner").actor_id).status_code == 422
    assert (
        h.call(
            "POST",
            path + "/assessments",
            "owner",
            {
                "submission_id": sub["submission_id"],
                "profile_ref": {"id": h.profiles["reconciliation"], "version": 1},
                "expected_review_token": current["review_token"],
            },
        ).status_code
        == 404
    )
    assert h.call("GET", "work/memberships", "reviewer").status_code == 403


def test_concerns_invalidate_review_not_decision_and_require_resolution_authority(service_demo):
    h = service_demo
    path, _, sub, current = h.ready()
    concern = h.call(
        "POST",
        "work/concerns",
        "reviewer",
        {
            "case_id": sub["case_id"],
            "assessment_id": current["assessment_id"],
            "finding_id": "finding_primary",
            "category": "interpretation",
            "message": "The profile may omit an important consequence.",
        },
    ).json()
    assert h.decide(path, current).status_code == 409
    current = h.call("GET", path + "/review").json()
    assert current["concerns"][0]["version"] == 1
    assert h.decide(path, current).status_code == 201
    response = {
        "expected_concern_version": 1,
        "message": "Independent evidence supports the interpretation.",
        "resolve": True,
    }
    route = "work/concerns/" + concern["concern_id"] + "/responses"
    assert h.call("POST", route, "reviewer", response).status_code == 403
    assert h.call("POST", route, "approver", response).status_code == 201
    assert h.call("POST", route, "approver", response).status_code == 409
    current = h.call("GET", path + "/review").json()
    assert current["state"] == "approved" and current["concerns"][0]["resolved"]


def test_late_host_reports_do_not_change_authorization(service_demo):
    h = service_demo
    path, body, _, current = h.ready()
    decision = h.decide(path, current).json()
    current = h.call("GET", path + "/review").json()
    assert (
        h.call(
            "POST",
            path + "/decisions/" + decision["decision_id"] + "/revocations",
            "owner",
            {
                "expected_review_token": current["review_token"],
                "rationale": "Withdraw before host reports",
            },
        ).status_code
        == 201
    )
    base = {"decision_id": decision["decision_id"], "occurred_at": datetime.now(UTC).isoformat()}
    assert (
        h.call(
            "POST",
            path + "/host-reports",
            "work-host",
            {**base, "type": "acknowledged", "details": {}},
        ).status_code
        == 201
    )
    report = h.call(
        "POST",
        path + "/host-reports",
        "work-host",
        {
            **base,
            "type": "execution_reported",
            "details": {
                "host_action_id": "action-1",
                "host_revision": body["host_revision"],
                "proposed_action": body["proposed_action"],
                "status": "succeeded",
            },
        },
    )
    assert (
        report.status_code == 201 and not report.json()["payload"]["matches_current_authorization"]
    )
    assert h.call("GET", path + "/review").json()["state"] == "revoked"
    events = h.call("GET", "work/events?case_id=" + current["case_id"]).json()["items"]
    assert {"host.acknowledged", "host.execution_reported"} <= {e["event_type"] for e in events}
    assert not any(e["event_type"] == "request.completed" for e in events)


def test_expiry_exceptions_conditions_and_profile_publication(service_demo, monkeypatch):
    h = service_demo
    path, _, sub, current = h.ready(supported=False)
    assert h.decide(path, current, "yes", "owner").status_code == 422
    definition = profile("work", Principal("reviewpoint-local-demo", "owner").actor_id).model_dump(
        mode="json"
    )
    definition["definition"]["requirements"][0]["exception"]["allowed_statuses"] = ["unmet"]
    definition["definition"]["review_rules"]["permitted_condition_types"] = ["host_check"]
    new = h.call("POST", "work/profiles", "owner", definition).json()
    assert h.call("GET", path + "/review").json()["profile_ref"]["id"] == h.profiles["work"]
    assert (
        h.call(
            "POST",
            path + "/assessments",
            "owner",
            {
                "submission_id": sub["submission_id"],
                "profile_ref": {"id": new["profile_id"], "version": 1},
                "expected_review_token": current["review_token"],
            },
        ).status_code
        == 202
    )
    h.service.process_one()
    current = h.call("GET", path + "/review").json()
    exception = [{"requirement_id": "primary", "rationale": "Explicitly accepted demo exception"}]
    assert h.decide(path, current, "yes", "approver", exceptions=exception).status_code == 422
    condition = [
        {
            "id": "manual",
            "type": "host_check",
            "description": "Manual handoff confirmed",
            "parameters": {"check_id": "manual_handoff_confirmed"},
        }
    ]
    decided = h.decide(path, current, "yes", "owner", exceptions=exception, conditions=condition)
    assert decided.status_code == 201, decided.text
    assert h.call("GET", path + "/review").json()["state"] == "approved_with_conditions"
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    monkeypatch.setattr("reviewpoint.service.now", lambda: future)
    assert h.call("GET", path + "/review").json()["state"] == "expired"


def test_storage_rollback_backup_and_newer_schema(service_demo, tmp_path, monkeypatch):
    h = service_demo
    path, _, _, current = h.ready()
    import reviewpoint.service as module

    original = module.event

    def broken(c, project, actor, kind, *args, **kwargs):
        if kind == "decision.recorded":
            raise OSError("injected failure")
        return original(c, project, actor, kind, *args, **kwargs)

    monkeypatch.setattr(module, "event", broken)
    with pytest.raises(OSError):
        h.decide(path, current)
    assert h.service.store.verify()["decisions"] == 0
    target = tmp_path / "backup.sqlite"
    h.service.store.backup(target)
    assert Store(target).verify() == h.service.store.verify()
    with h.service.store.transaction(write=True) as c:
        c.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="unsupported"):
        h.service.store.initialize()


def test_body_hash_scope_and_size_validation(service_demo):
    h = service_demo
    body = submission("work").model_dump(mode="json")
    body["evidence"][0]["content_hash"] = "sha256:bad"
    assert h.call("POST", "work/submissions", "work-host", body).status_code == 422
    del body["evidence"][0]["content_hash"]
    body["evidence"][0]["captured_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert h.call("POST", "work/submissions", "work-host", body).status_code == 422
    response = h.client.post("/api/v1/projects/work/submissions", content=b"x" * (5 * 1048576 + 1))
    assert response.status_code == 413
    assert h.service.store.verify()["submissions"] == 0


class FakeTransport:
    def __init__(self, valid=True):
        self.calls = 0
        self.valid = valid

    def complete(self, **kwargs):
        self.calls += 1
        self.request = json.loads(kwargs["user"])
        return ProviderResponse(
            json.dumps(
                {
                    "status": "met",
                    "explanation": "Supplied item counts agree.",
                    "references": [{"source": "work", "pointer": "/declared"}]
                    if self.valid
                    else [],
                    "limits": ["Synthetic interpretation, not independently validated."],
                }
            ),
            "response-demo",
            kwargs["model"],
            {"input_tokens": 20, "output_tokens": 10},
        )


def test_semantic_validation_failure_and_no_duplicate_provider_call(service_demo):
    h = service_demo
    transport = FakeTransport()
    h.service.transport = transport
    definition = profile(
        "work", Principal("reviewpoint-local-demo", "owner").actor_id, semantic=True
    )
    pid = h.call("POST", "work/profiles", "owner", definition.model_dump(mode="json")).json()[
        "profile_id"
    ]
    h.profiles["work"] = pid
    path, _, _, reserved = h.start()
    h.service.process_one()
    assert transport.calls == 1
    assert (
        transport.request["submission"]["proposed_action"]
        == submission("work").model_dump(mode="json")["proposed_action"]
    )
    assert transport.request["profile_context"]["risks_in_priority_order"]
    assert transport.request["profile_context"]["scope"]["work_types"]
    assert h.call("GET", path + "/review").json()["evaluation_status"] == "completed"
    transport.valid = False
    path, _, _, _ = h.start(external_id="bad-interpretation")
    h.service.process_one()
    current = h.call("GET", path + "/review").json()
    assert current["state"] == "evaluation_failed" and current["recommendation"] is None


def test_rank_applicability_and_missing_reference_are_independent():
    owner = Principal("reviewpoint-local-demo", "owner").actor_id
    source = submission("mapping").model_dump(mode="json")
    source["action"] = source.pop("proposed_action")
    definition = profile("mapping", owner).model_dump(mode="json")["definition"]
    first, _ = evaluate(source, definition, datetime.now(UTC).isoformat())
    assert first["recommendation"]["answer"] == "yes"
    assert first["requirement_results"][1]["status"] == "not_applicable"
    definition["risks"].reverse()
    second, _ = evaluate(source, definition, datetime.now(UTC).isoformat())
    assert second["recommendation"] == first["recommendation"]
    del source["work"]["account_type"]
    missing, _ = evaluate(source, definition, datetime.now(UTC).isoformat())
    assert missing["recommendation"]["answer"] == "no"
    assert missing["requirement_results"][1]["status"] == "unknown"


@pytest.mark.parametrize("model_case", ["unknown_pointer", "mixed_locator", "invented_quote"])
def test_invalid_model_references_fail_and_retain_call_metadata(service_demo, model_case):
    h = service_demo

    class InvalidReferenceTransport:
        def complete(self, **kwargs):
            references = {
                "unknown_pointer": {"source": "work", "pointer": "/does-not-exist"},
                "mixed_locator": {
                    "source": "work",
                    "pointer": "/declared",
                    "evidence_id": "source",
                },
                "invented_quote": {
                    "source": "evidence",
                    "evidence_id": "source",
                    "quote": "invented support",
                },
            }
            return ProviderResponse(
                json.dumps(
                    {
                        "status": "met",
                        "explanation": "Unsupported claim",
                        "references": [references[model_case]],
                        "limits": [],
                    }
                ),
                "rejected-demo",
                kwargs["model"],
                {"input_tokens": 5},
            )

    h.service.transport = InvalidReferenceTransport()
    definition = profile(
        "work", Principal("reviewpoint-local-demo", "owner").actor_id, semantic=True
    )
    h.profiles["work"] = h.call(
        "POST", "work/profiles", body=definition.model_dump(mode="json")
    ).json()["profile_id"]
    path, _, _, reserved = h.start()
    h.service.process_one()
    result = h.call("GET", path + "/assessments/" + reserved["assessment_id"]).json()
    assert result["status"] == "failed" and result["recommendation"] is None
    assert result["run"]["calls"][0]["response_id"] == "rejected-demo"
    assert result["run"]["calls"][0]["usage"]["input_tokens"] == 5
    assert result["run"]["calls"][0]["validation_status"] == "rejected"
    assert "Unsupported claim" not in json.dumps(result)
    assert "request" not in result["run"]["calls"][0]
    listed = h.call("GET", path + "/assessments").json()
    assert "Unsupported claim" not in json.dumps(listed)
    with h.service.store.transaction() as c:
        saved = json.loads(
            c.execute(
                "SELECT run_json FROM assessments WHERE assessment_id=?",
                (reserved["assessment_id"],),
            ).fetchone()[0]
        )
    assert "Unsupported claim" in saved["calls"][0]["rejected_output"]


def test_all_api_routes_require_identity(service_demo):
    h = service_demo
    path, _, sub, current = h.ready()
    spec = h.client.get("/openapi.json").json()
    for route, operations in spec["paths"].items():
        actual = route.replace("{project}", "work").replace("{case}", sub["case_id"])
        actual = actual.replace("{profile}", h.profiles["work"]).replace("{number}", "1")
        actual = (
            actual.replace("{record}", current["assessment_id"])
            .replace("{decision}", "unknown")
            .replace("{concern}", "unknown")
        )
        for method in operations:
            if method not in {"get", "post", "put", "patch"}:
                continue
            response = h.client.request(
                method,
                actual,
                json={} if method != "get" else None,
                headers={"Idempotency-Key": "anonymous"},
            )
            assert response.status_code == 401, (route, method, response.text)


def test_generated_contracts_and_wire_responses(service_demo):
    import jsonschema

    from reviewpoint.contracts import export

    root = Path(__file__).resolve().parents[1]
    assert export(root / "schemas", check=True) >= 50
    h = service_demo
    path, _, sub, current = h.ready()
    decision = h.decide(path, current).json()
    for name, value in [
        ("Review", h.call("GET", path + "/review").json()),
        ("DecisionRecord", decision),
        ("SubmissionRecord", h.call("GET", path + "/submissions/" + sub["submission_id"]).json()),
    ]:
        schema = json.loads((root / "schemas" / (name + ".schema.json")).read_text())
        jsonschema.Draft202012Validator(schema).validate(value)


def test_profile_and_metadata_versions_conflict(service_demo):
    h = service_demo
    project = h.call("GET", "work").json()
    edit = {
        "name": "Work demo",
        "expected_version": project["version"],
        "reason": "Clarify demo label",
    }
    assert h.call("PATCH", "work", body=edit).status_code == 200
    assert h.call("PATCH", "work", body=edit).status_code == 409
    p = h.call("GET", "work/profiles/" + h.profiles["work"] + "/versions/1").json()
    body = {k: p[k] for k in ("name", "owner_id", "definition")}
    body.update(expected_latest_version=1, reason="Reorder priorities")
    body["definition"]["risks"].reverse()
    route = "work/profiles/" + h.profiles["work"] + "/versions"
    assert h.call("POST", route, body=body).status_code == 201
    assert h.call("POST", route, body=body).status_code == 409
    assert h.call("POST", route, who="approver", body=body).status_code == 403


def test_semantic_reservation_retry_only_calls_provider_once(service_demo):
    h = service_demo
    transport = FakeTransport()
    h.service.transport = transport
    definition = profile(
        "work", Principal("reviewpoint-local-demo", "owner").actor_id, semantic=True
    )
    pid = h.call("POST", "work/profiles", body=definition.model_dump(mode="json")).json()[
        "profile_id"
    ]
    sub = h.call(
        "POST", "work/submissions", "work-host", submission("work").model_dump(mode="json")
    ).json()
    path = "work/cases/" + sub["case_id"]
    body = {
        "submission_id": sub["submission_id"],
        "profile_ref": {"id": pid, "version": 1},
        "expected_review_token": sub["review_token"],
    }
    first = h.call("POST", path + "/assessments", "work-host", body, "repeat")
    h.service.process_one()
    assert h.call("POST", path + "/assessments", "work-host", body, "repeat").json() == first.json()
    assert not h.service.process_one() and transport.calls == 1


def test_unknown_optional_and_stale_evidence():
    owner = Principal("reviewpoint-local-demo", "owner").actor_id
    source = submission("release").model_dump(mode="json")
    source["action"] = source.pop("proposed_action")
    source["evidence"][0]["captured_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    definition = profile("release", owner).model_dump(mode="json")["definition"]
    result, _ = evaluate(source, definition, datetime.now(UTC).isoformat())
    assert result["recommendation"]["answer"] == "no"
    assert result["requirement_results"][0]["status"] == "unknown"


def test_independent_challenge_exposes_a_defective_profile(service_demo):
    h = service_demo
    good_profile = profile(
        "work", Principal("reviewpoint-local-demo", "owner").actor_id
    ).model_dump(mode="json")
    # Deliberately bad definition compares the declared count to itself.
    good_profile["definition"]["requirements"][0]["check"]["parameters"]["right"] = "/work/declared"
    pid = h.call("POST", "work/profiles", body=good_profile).json()["profile_id"]
    h.profiles["work"] = pid
    path, _, sub, current = h.ready(supported=False)
    assert current["recommendation"]["answer"] == "yes"
    # Independent source count establishes that this illustrative case should remain a hold.
    assert h.decide(path, current, answer="no").status_code == 201
    concern = h.call(
        "POST",
        "work/concerns",
        "reviewer",
        {
            "profile_ref": {"id": pid, "version": 1},
            "category": "profile",
            "message": (
                "Declared=4 and supported=3: this self-comparison cannot establish completeness."
            ),
        },
    )
    assert concern.status_code == 201
    after = h.call("GET", path + "/review").json()
    assert after["state"] == "declined" and len(after["concerns"]) == 1


def test_foreign_key_enforcement(service_demo):
    with service_demo.service.store.transaction(write=True) as c:
        with pytest.raises(__import__("sqlite3").IntegrityError):
            c.execute(
                "INSERT INTO project_memberships(project_id,actor_id,role,version,"
                "changed_by,changed_at) VALUES ('absent','x','owner',1,'x','now')"
            )


def test_second_server_cannot_recover_an_active_workers_attempt(service_demo):
    h = service_demo
    h.start()
    with h.service.store.server_lock():
        with pytest.raises(ValueError, match="another service process"):
            with h.service.store.server_lock():
                h.service.recover()
    assert h.service.store.verify()["assessments"] == 1


def test_event_pages_pin_history_bound_and_recheck_scope(service_demo):
    h = service_demo
    path, _, sub, current = h.ready()
    route = "work/events?limit=1&case_id=" + sub["case_id"]
    first = h.call("GET", route).json()
    bound = first["upper_sequence"]
    assert first["next_cursor"]
    assert h.decide(path, current).status_code == 201
    events = list(first["items"])
    cursor = first["next_cursor"]
    while cursor:
        response = h.call("GET", route + "&cursor=" + cursor)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["upper_sequence"] == bound
        events.extend(page["items"])
        cursor = page["next_cursor"]
    assert len({e["event_id"] for e in events}) == len(events)
    assert max(e["event_seq"] for e in events) == bound
    later = h.call("GET", route + "&after_sequence=" + str(bound)).json()
    assert later["items"][0]["event_seq"] > bound
    assert h.call("GET", "reconciliation/events?cursor=" + first["next_cursor"]).status_code == 400
    for endpoint in ("work/memberships", "work/profiles", "work/cases"):
        assert h.call("GET", endpoint + "?limit=0").status_code == 422


def test_malformed_host_check_metadata_is_rejected(service_demo):
    h = service_demo
    response = h.call(
        "PATCH",
        "work",
        body={
            "expected_version": 1,
            "reason": "Invalid shape",
            "metadata": {"host_checks": ["unsupported"]},
        },
    )
    assert response.status_code == 422
    assert h.call("GET", "work").json()["version"] == 1


def test_restart_fails_interrupted_attempt_without_approval_fallback(service_demo):
    h = service_demo
    path, _, _, attempt = h.start()
    h.service.recover()
    current = h.call("GET", path + "/review").json()
    assert current["evaluation_status"] == "failed"
    assert current["recommendation"] is None
    assert not h.service.process_one()
    assert (
        h.call("GET", attempt["status_url"].removeprefix("/api/v1/projects/")).json()["status"]
        == "failed"
    )


def test_nonfinite_domain_json_is_rejected_before_storage(service_demo):
    h = service_demo
    body = submission("work").model_dump(mode="json")
    body["work"]["declared"] = float("nan")
    response = h.client.post(
        "/api/v1/projects/work/submissions",
        content=json.dumps(body),
        headers={
            "Authorization": "Bearer " + h.tokens["work-host"],
            "Idempotency-Key": "not-finite",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422
    assert h.service.store.verify()["submissions"] == 0


@pytest.mark.parametrize("who", ["reviewer", "approver", "work-host", "owner"])
def test_membership_events_follow_owner_visibility_before_pagination(service_demo, who):
    h = service_demo
    path, _, _, current = h.ready()
    assert h.decide(path, current).status_code == 201
    actor = Principal("reviewpoint-local-demo", "reviewer").actor_id
    assert (
        h.call(
            "PUT",
            "work/memberships",
            body={
                "actor_id": actor,
                "role": "reviewer",
                "active": True,
                "expected_version": 1,
                "reason": "Synthetic administrative detail",
            },
        ).status_code
        == 200
    )
    full = h.call("GET", "work/events?limit=100", who).json()
    membership = [e for e in full["items"] if e["event_type"].startswith("membership.")]
    assert bool(membership) == (who == "owner")
    if who == "owner":
        assert {e["event_type"] for e in membership} == {"membership.created", "membership.changed"}
    else:
        assert "Synthetic administrative detail" not in json.dumps(full)
        assert h.call("GET", "work/memberships", who).status_code == 403
    assert any(e["event_type"].startswith("decision.") and e["actor_id"] for e in full["items"])
    assert full["upper_sequence"] == max(e["event_seq"] for e in full["items"])
    route = "work/events?limit=1"
    first = h.call("GET", route, who).json()
    items, cursor = list(first["items"]), first["next_cursor"]
    while cursor:
        result = h.call("GET", route + "&cursor=" + cursor, who)
        assert result.status_code == 200
        page = result.json()
        assert page["upper_sequence"] == first["upper_sequence"]
        items.extend(page["items"])
        cursor = page["next_cursor"]
    assert items == full["items"]
    incremental = h.call(
        "GET", "work/events?limit=100&after_sequence=" + str(first["items"][0]["event_seq"]), who
    ).json()
    assert incremental["items"] == full["items"][1:]


def test_event_cursor_rejects_changed_visibility(service_demo):
    h = service_demo
    h.ready()
    route = "work/events?limit=1"
    reader_cursor = h.call("GET", route, "reviewer").json()["next_cursor"]
    assert reader_cursor
    actor = Principal("reviewpoint-local-demo", "reviewer").actor_id
    for version, role, previous_cursor in [(1, "owner", reader_cursor), (2, "reviewer", None)]:
        if previous_cursor is None:
            previous_cursor = h.call("GET", route, "reviewer").json()["next_cursor"]
        assert (
            h.call(
                "PUT",
                "work/memberships",
                body={
                    "actor_id": actor,
                    "role": role,
                    "active": True,
                    "expected_version": version,
                    "reason": "Change visibility",
                },
            ).status_code
            == 200
        )
        result = h.call("GET", route + "&cursor=" + previous_cursor, "reviewer")
        assert result.status_code == 400
        assert result.json()["error"]["code"] == "invalid_cursor"
    owner_cursor = h.call("GET", route).json()["next_cursor"]
    assert h.call("GET", route + "&cursor=" + owner_cursor, "work-host").status_code == 400


def test_event_cursor_rechecks_integration_scope(service_demo):
    h = service_demo
    h.ready()
    route = "work/events?limit=1"
    cursor = h.call("GET", route, "work-host").json()["next_cursor"]
    principal = h.identity.authenticate(h.tokens["work-host"])
    principal.grants["work"]["workflow_ids"].append("other-workflow")
    assert h.call("GET", route + "&cursor=" + cursor, "work-host").status_code == 400
    fresh = h.call("GET", route, "work-host").json()["next_cursor"]
    principal.grants["work"]["workflow_ids"].reverse()
    assert h.call("GET", route + "&cursor=" + fresh, "work-host").status_code == 200
