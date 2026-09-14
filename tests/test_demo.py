"""The single example uses real API transitions, with no model/network dependency."""

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reviewpoint.app import create_app
from reviewpoint.cli import app as cli
from reviewpoint.demo import PROJECT, load, prepare, seed, submission
from reviewpoint.example_host import attach
from reviewpoint.storage import now


@pytest.fixture
def example(tmp_path):
    path = tmp_path / "workspace"
    seed(path)
    case_id = prepare(path)
    service, identity = load(path)
    app = create_app(service, identity, worker=False)
    attach(app, service, identity, path, case_id)
    tokens = json.loads((path / "demo-credentials.json").read_text())
    with TestClient(app) as client:
        yield path, service, client, tokens, case_id


def test_interactive_hold_revision_proceed_handoff_and_resume(example):
    path, service, client, tokens, case_id = example
    base = f"/api/v1/projects/{PROJECT}"
    case = base + "/cases/" + case_id
    counter = 0

    def call(method, url, body=None, key=None):
        nonlocal counter
        counter += 1
        r = client.request(
            method,
            url,
            json=body,
            headers={
                "Authorization": "Bearer " + tokens["owner"],
                "Idempotency-Key": key or str(counter),
            },
        )
        assert r.status_code < 300, r.text
        return r.json()

    current = call("GET", case + "/review")
    assert current["recommendation"]["answer"] == "no"
    assert current["current_decision"] is None
    assert call("GET", "/example-host")["fields"]
    assert call("GET", base)["actor_id"].endswith('"owner"]')

    def decide(answer):
        return call(
            "POST",
            case + "/decisions",
            {
                "assessment_id": current["assessment_id"],
                "expected_review_token": current["review_token"],
                "answer": answer,
                "rationale": "Independent human test decision",
                "supersedes_decision_id": current["current_decision"]["decision_id"]
                if current["current_decision"]
                else None,
            },
        )

    held = decide("no")
    frozen = call("GET", current["evidence_url"])
    new_work = {**frozen["work"], "supplied_items": 4}
    body = submission(new_work, previous=frozen["submission_id"], revision=2).model_dump(
        mode="json"
    )
    revised = call("POST", "/example-host/submissions", body, "revision-2")
    assert call("POST", "/example-host/submissions", body, "revision-2") == revised
    current = call("GET", case + "/review")
    assert current["current_decision"] is None and current["assessment_id"] is None
    profiles = call("GET", base + "/profiles")["items"]
    p = profiles[0]
    call(
        "POST",
        case + "/assessments",
        {
            "submission_id": current["submission_id"],
            "profile_ref": {"id": p["profile_id"], "version": p["version"]},
            "expected_review_token": current["review_token"],
        },
    )
    assert service.process_one()
    current = call("GET", case + "/review")
    assert current["recommendation"]["answer"] == "yes"
    approved = decide("yes")
    handoff = {
        "submission_id": current["submission_id"],
        "decision_id": approved["decision_id"],
        "occurred_at": now(),
    }
    report = call("POST", "/example-host/handoff", handoff, "handoff")
    assert call("POST", "/example-host/handoff", handoff, "handoff") == report
    events = call("GET", base + "/events?case_id=" + case_id)["items"]
    assert len([e for e in events if e["event_type"] == "host.execution_reported"]) == 1
    assert report["payload"]["details"]["host_action_id"].startswith("simulation:")
    assert call("GET", case + "/decisions/" + held["decision_id"])["answer"] == "no"
    assert prepare(path) == case_id
    restarted, _ = load(path)
    assert restarted.store.verify()["decisions"] == 2
    assert len(call("GET", base + "/cases")["items"]) == 1


def test_demo_routes_require_human_authority_and_current_approval(example):
    path, service, client, tokens, case_id = example
    assert client.get("/example-host").status_code == 401

    def headers(who):
        return {"Authorization": "Bearer " + tokens[who], "Idempotency-Key": "attempt"}

    assert client.get("/example-host", headers=headers("host")).status_code == 403
    body = submission().model_dump(mode="json")
    assert (
        client.post("/example-host/submissions", headers=headers("reviewer"), json=body).status_code
        == 403
    )
    body["case_ref"]["external_case_id"] = "another-case"
    assert (
        client.post("/example-host/submissions", headers=headers("owner"), json=body).status_code
        == 422
    )
    assert (
        client.post(
            "/example-host/handoff",
            headers=headers("owner"),
            json={"submission_id": "old", "decision_id": "old", "occurred_at": now()},
        ).status_code
        == 409
    )
    core = create_app(service, load(path)[1], worker=False)
    with TestClient(core) as c:
        assert c.get("/example-host", headers=headers("owner")).status_code == 404


def test_guidelines_require_explicit_action_mapping_and_preserve_versions(example):
    _, _, client, tokens, _ = example
    headers = {"Authorization": "Bearer " + tokens["owner"], "Idempotency-Key": "publish"}
    base = f"/api/v1/projects/{PROJECT}/profiles"
    p = client.get(base, headers=headers).json()["items"][0]
    body = {k: p[k] for k in ("name", "owner_id", "definition")}
    body.update(reason="Reorder for a new evaluation", expected_latest_version=1)
    body["definition"]["risks"].reverse()
    body["definition"]["risks"][0]["applies_to"] = "both"
    r = client.post(base + "/" + p["profile_id"] + "/versions", headers=headers, json=body)
    assert r.status_code == 201, r.text
    old = client.get(base + "/" + p["profile_id"] + "/versions/1", headers=headers).json()
    assert old["definition"]["risks"][0]["id"] == "incomplete"
    assert r.json()["definition"]["risks"][0]["applies_to"] == "both"
    del body["definition"]["risks"][0]["applies_to"]
    assert (
        client.post(
            base + "/" + p["profile_id"] + "/versions", headers=headers, json=body
        ).status_code
        == 422
    )


def test_cli_offline_prepare_is_repeatable_and_backup_verifies(tmp_path):
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    args = ["demo", "--prepare-only", "--workspace", str(workspace)]
    first = runner.invoke(cli, args)
    assert first.exit_code == 0, first.output
    assert runner.invoke(cli, args).output == first.output
    assert runner.invoke(cli, ["verify", "--workspace", str(workspace)]).exit_code == 0
    assert (
        runner.invoke(
            cli, ["backup", str(tmp_path / "backup.sqlite3"), "--workspace", str(workspace)]
        ).exit_code
        == 0
    )
    assert runner.invoke(cli, ["init", "--workspace", str(workspace)]).exit_code != 0


def test_live_is_explicit_and_requires_a_model(tmp_path):
    workspace = tmp_path / "workspace"
    seed(workspace)
    with pytest.raises(ValueError, match="Set model"):
        load(workspace, live=True)
    assert load(workspace)[0].transport is None


def test_demo_preparation_cannot_compete_with_a_running_server(tmp_path):
    workspace = tmp_path / "workspace"
    seed(workspace)
    service, _ = load(workspace)
    with service.store.server_lock():
        with pytest.raises(ValueError, match="another service process"):
            prepare(workspace)
    assert service.store.verify()["cases"] == 0
