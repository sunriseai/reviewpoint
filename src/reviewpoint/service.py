"""Transactional application operations shared by HTTP, worker and demo tooling."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from reviewpoint.canonical import content_digest, digest
from reviewpoint.openai_transport import DEFAULT_MODEL, Transport

from . import models as m
from .evaluation import EVALUATOR_VERSION, EvaluationFailure, evaluate, validate_definition
from .idempotency import validate_key
from .identity import Principal, ServiceError, access, host_access
from .storage import Store, dumps, event, insert, now, uid, unpack


def fail(status: int, code: str, message: str) -> None:
    raise ServiceError(status, code, message)


def one(c: sqlite3.Connection, table: str, project: str, **keys: Any) -> dict[str, Any]:
    row = c.execute(
        f"SELECT * FROM {table} WHERE project_id=?" + "".join(f" AND {k}=?" for k in keys),
        (project, *keys.values()),
    ).fetchone()
    if row is None:
        fail(404, "not_found", "Project or resource not found.")
    return unpack(row)


def get_case(c: sqlite3.Connection, p: Principal, project: str, case: str) -> dict[str, Any]:
    result = one(c, "cases", project, case_id=case)
    host_access(p, project, result)
    return result


def version(c: sqlite3.Connection, project: str, kind: str, related: str | None = None) -> int:
    if related:
        return int(
            1
            + c.execute(
                (
                    "SELECT COUNT(*) FROM events WHERE project_id=? AND event_type=? "
                    "AND related_event_id=?"
                ),
                (project, kind, related),
            ).fetchone()[0]
        )
    return int(
        1
        + c.execute(
            "SELECT COUNT(*) FROM events WHERE project_id=? AND event_type=?", (project, kind)
        ).fetchone()[0]
    )


def check_version(actual: int, expected: int) -> None:
    if actual != expected:
        fail(409, "stale_version", "This record changed. Reload before saving.")


def concerns(
    c: sqlite3.Connection,
    project: str,
    case: str | None,
    profile: str | None = None,
    pv: int | None = None,
) -> list[dict[str, Any]]:
    rows = c.execute(
        (
            "SELECT * FROM events WHERE project_id=? AND "
            "event_type='concern.raised' AND (case_id=? OR (profile_id=? AND "
            "profile_version=?)) ORDER BY event_seq"
        ),
        (project, case, profile, pv),
    ).fetchall()
    result = []
    for row in rows:
        item = unpack(row)
        responses = [
            unpack(r)
            for r in c.execute(
                (
                    "SELECT * FROM events WHERE project_id=? AND related_event_id=? "
                    "AND event_type='concern.responded' ORDER BY event_seq"
                ),
                (project, item["event_id"]),
            )
        ]
        item.update(
            concern_id=item["event_id"],
            version=1 + len(responses),
            responses=responses,
            resolved=any(r["payload"]["resolve"] for r in responses),
        )
        result.append(item)
    return result


def review(
    c: sqlite3.Connection, project: str, case: str, authority: dict[str, Any]
) -> dict[str, Any]:
    current = unpack(
        c.execute(
            "SELECT * FROM current_case_review WHERE project_id=? AND case_id=?", (project, case)
        ).fetchone()
    )
    sub = (
        one(c, "submissions", project, submission_id=current["submission_id"])
        if current.get("submission_id")
        else None
    )
    assessment = (
        one(c, "assessments", project, assessment_id=current["assessment_id"])
        if current.get("assessment_id")
        else None
    )
    decision = (
        one(c, "decisions", project, decision_id=current["decision_id"])
        if current.get("decision_id")
        else None
    )
    discussion = concerns(
        c, project, case, current.get("profile_id"), current.get("profile_version")
    )
    stamp = now()
    state = "awaiting_evaluation"
    if assessment:
        state = {
            "pending": "evaluating",
            "failed": "evaluation_failed",
            "completed": "awaiting_decision",
        }[assessment["status"]]
    if decision:
        if decision["kind"] == "revocation":
            state = "revoked"
        elif decision["answer"] == "no":
            state = "declined"
        elif decision["valid_until"] and datetime.fromisoformat(
            decision["valid_until"]
        ) <= datetime.fromisoformat(stamp):
            state = "expired"
        else:
            state = "approved_with_conditions" if decision["conditions"] else "approved"
    token = digest(
        {
            "submission": current.get("submission_id"),
            "assessment": current.get("assessment_id"),
            "status": current.get("evaluation_status"),
            "result_hash": assessment.get("result_hash") if assessment else None,
            "decision": current.get("decision_id"),
            "concerns": [(r["event_id"], r["version"]) for r in discussion],
        }
    )
    role = authority["role"]
    actions = []
    if role in ("reviewer", "approver", "owner"):
        actions.append("raise_concern")
    has_decisions = (
        sub
        and c.execute(
            (
                "SELECT 1 FROM decisions d JOIN assessments a ON "
                "a.assessment_id=d.assessment_id WHERE a.submission_id=? LIMIT 1"
            ),
            (sub["submission_id"],),
        ).fetchone()
    )
    if role == "owner" or (
        not has_decisions
        and (role == "approver" or "evaluate" in authority.get("capabilities", []))
    ):
        actions.append("evaluate")
    if (
        assessment
        and assessment["status"] == "completed"
        and (role == "owner" or role == "approver" and decision is None)
    ):
        actions.append("record_no")
        if datetime.fromisoformat(assessment["result"]["valid_until"]) > datetime.fromisoformat(
            stamp
        ):
            profile = one(
                c,
                "profile_versions",
                project,
                profile_id=assessment["profile_id"],
                version=assessment["profile_version"],
            )
            reqs = {r["id"]: r for r in profile["definition"]["requirements"]}
            if all(
                r["status"] in ("met", "not_applicable")
                or role == "owner"
                and r["status"] in reqs[r["requirement_id"]]["exception"]["allowed_statuses"]
                for r in assessment["result"]["requirement_results"]
            ):
                actions.append("record_yes")
    if role == "owner" and decision and decision["kind"] == "decision":
        actions.append("revoke_decision")
    result = assessment.get("result") if assessment else None
    return {
        "case_id": case,
        "project_id": project,
        "state": state,
        "observed_at": stamp,
        "review_token": token,
        "submission_id": current.get("submission_id"),
        "host_revision": current.get("host_revision"),
        "submission_hash": current.get("submission_hash"),
        "proposed_action": sub["action"] if sub else None,
        "summary": sub["summary"] if sub else None,
        "assessment_id": current.get("assessment_id"),
        "evaluation_status": current.get("evaluation_status"),
        "profile_ref": {"id": current.get("profile_id"), "version": current.get("profile_version")}
        if assessment
        else None,
        "recommendation": result["recommendation"] if result else None,
        "result": result,
        "error": assessment.get("error") if assessment else None,
        "current_decision": decision,
        "concerns": discussion,
        "allowed_actions": actions,
        "evidence_url": (
            f"/api/v1/projects/{project}/cases/{case}/submissions/" + sub["submission_id"]
        )
        if sub
        else None,
    }


def check_review(current: dict[str, Any], token: str) -> None:
    if current["review_token"] != token:
        fail(409, "stale_review", "This review changed. Reload before deciding.")


class Service:
    def __init__(
        self, store: Store, transport: Transport | None = None, model: str = DEFAULT_MODEL
    ):
        self.store, self.transport, self.model = store, transport, model

    def mutate(
        self,
        p: Principal,
        project: str,
        capability: str,
        operation: str,
        key: str,
        body: m.Model,
        action: Callable[[sqlite3.Connection, dict[str, Any], str], tuple[int, dict[str, Any]]],
        case: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        key = validate_key(key)
        fingerprint = digest(body)
        request_key = digest([p.actor_id, operation, key])
        with self.store.transaction(write=True) as c:
            authority = access(c, p, project, capability)
            if case:
                get_case(c, p, project, case)
            previous = c.execute(
                (
                    "SELECT payload_json FROM events WHERE project_id=? AND "
                    "source_id=? AND source_event_key=?"
                ),
                (project, p.actor_id, request_key),
            ).fetchone()
            if previous:
                receipt = json.loads(previous[0])
                if receipt["fingerprint"] != fingerprint:
                    fail(409, "idempotency_conflict", "This key was used with different content.")
                return receipt["status"], receipt["response"]
            status, result = action(c, authority, request_key)
            event(
                c,
                project,
                p.actor_id,
                "request.completed",
                {
                    "fingerprint": fingerprint,
                    "operation": operation,
                    "status": status,
                    "response": result,
                },
                case=case,
                source_key=request_key,
            )
            return status, result

    def project_edit(
        self, p: Principal, project: str, key: str, body: m.ProjectEdit
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            check_version(version(c, project, "project.changed"), body.expected_version)
            old = one(c, "projects", project)
            c.execute(
                "UPDATE projects SET name=?,metadata_json=? WHERE project_id=?",
                (
                    body.name or old["name"],
                    dumps(body.metadata if body.metadata is not None else old["metadata"]),
                    project,
                ),
            )
            new = one(c, "projects", project)
            event(
                c,
                project,
                p.actor_id,
                "project.changed",
                {"before": old, "after": new, "reason": body.reason},
            )
            return 200, {**new, "version": body.expected_version + 1}

        return self.mutate(p, project, "owner", "project.edit", key, body, action)

    def membership(
        self, p: Principal, project: str, key: str, body: m.MembershipEdit
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            try:
                identity = json.loads(body.actor_id)
                if (
                    len(identity) != 3
                    or identity[0] != "human"
                    or any(not isinstance(v, str) or not v for v in identity)
                ):
                    raise ValueError
                if dumps(identity) != body.actor_id:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ServiceError(
                    422, "invalid_actor", "Use a canonical external human identity."
                ) from exc
            old = unpack(
                c.execute(
                    "SELECT * FROM project_memberships WHERE project_id=? AND actor_id=?",
                    (project, body.actor_id),
                ).fetchone()
            )
            check_version(old.get("version", 0), body.expected_version)
            if (
                old.get("role") == "owner"
                and old.get("active")
                and (body.role != "owner" or not body.active)
            ):
                if (
                    c.execute(
                        (
                            "SELECT COUNT(*) FROM project_memberships WHERE project_id=? AND "
                            "role='owner' AND active=1"
                        ),
                        (project,),
                    ).fetchone()[0]
                    == 1
                ):
                    fail(409, "last_owner", "The last active owner cannot be removed.")
            values = (
                body.role,
                int(body.active),
                body.expected_version + 1,
                p.actor_id,
                now(),
                project,
                body.actor_id,
            )
            if old:
                c.execute(
                    (
                        "UPDATE project_memberships SET "
                        "role=?,active=?,version=?,changed_by=?,changed_at=? WHERE "
                        "project_id=? AND actor_id=?"
                    ),
                    values,
                )
            else:
                c.execute(
                    (
                        "INSERT INTO "
                        "project_memberships(role,active,version,changed_by,changed_at,project_id,actor_id)"
                        " VALUES (?,?,?,?,?,?,?)"
                    ),
                    values,
                )
            new = one(c, "project_memberships", project, actor_id=body.actor_id)
            event(
                c,
                project,
                p.actor_id,
                "membership.changed",
                {"before": old, "after": new, "reason": body.reason},
            )
            return (200 if old else 201), new

        return self.mutate(p, project, "owner", "membership.edit", key, body, action)

    def publish(
        self,
        p: Principal,
        project: str,
        key: str,
        body: m.PublishProfile,
        profile: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            validate_definition(body.definition)
            owner = one(c, "project_memberships", project, actor_id=body.owner_id)
            if owner["role"] != "owner" or not owner["active"]:
                fail(422, "invalid_owner", "The profile owner must be an active project owner.")
            pid, number = profile or uid("profile"), 1
            if profile:
                latest = c.execute(
                    "SELECT MAX(version) FROM profile_versions WHERE project_id=? AND profile_id=?",
                    (project, profile),
                ).fetchone()[0]
                if latest is None:
                    fail(404, "not_found", "Profile not found.")
                assert isinstance(body, m.PublishVersion)
                check_version(latest, body.expected_latest_version)
                number = latest + 1
            insert(
                c,
                "profile_versions",
                project_id=project,
                profile_id=pid,
                version=number,
                name=body.name,
                owner_id=body.owner_id,
                published_by=p.actor_id,
                published_at=now(),
                definition_json=dumps(body.definition),
                content_hash="",
            )
            saved = one(c, "profile_versions", project, profile_id=pid, version=number)
            event(
                c,
                project,
                p.actor_id,
                "profile.published",
                {"reason": body.reason, "content_hash": saved["content_hash"]},
                profile=pid,
                version=number,
            )
            return 201, saved

        return self.mutate(
            p, project, "owner", f"profile.publish/{profile or ''}", key, body, action
        )

    def submit(
        self, p: Principal, project: str, key: str, body: m.Submission
    ) -> tuple[int, dict[str, Any]]:
        host_access(p, project, body.case_ref.model_dump())

        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            capture = body.model_dump(mode="json", exclude={"expected_submission_id"})
            for evidence in capture["evidence"]:
                if datetime.fromisoformat(evidence["captured_at"]) > datetime.fromisoformat(now()):
                    fail(422, "future_evidence", "Capture time cannot be in the future.")
                actual_hash = content_digest(evidence["content"])
                if evidence["content_hash"] and evidence["content_hash"] != actual_hash:
                    fail(422, "hash_mismatch", "Evidence content hash does not match.")
                evidence["content_hash"] = actual_hash
            input_hash = digest(capture)
            reference = body.case_ref.model_dump()
            existing = c.execute(
                (
                    "SELECT * FROM cases WHERE project_id=? AND host_id=? AND "
                    "workflow_id=? AND external_case_id=? AND checkpoint_key=?"
                ),
                (project, *reference.values()),
            ).fetchone()
            case = existing["case_id"] if existing else uid("case")
            if existing:
                old = c.execute(
                    "SELECT * FROM submissions WHERE case_id=? AND host_revision=?",
                    (case, body.host_revision),
                ).fetchone()
                if old:
                    receipt = c.execute(
                        (
                            "SELECT payload_json FROM events WHERE case_id=? AND "
                            "event_type='submission.received'"
                        ),
                        (case,),
                    ).fetchall()
                    saved = next(
                        json.loads(r[0])
                        for r in receipt
                        if json.loads(r[0])["submission_id"] == old["submission_id"]
                    )
                    if saved["input_hash"] != input_hash:
                        fail(
                            409,
                            "host_revision_conflict",
                            "Host revision already identifies different content.",
                        )
                    return 200, saved["response"]
            latest = c.execute(
                (
                    "SELECT submission_id,revision FROM submissions WHERE case_id=? "
                    "ORDER BY revision DESC LIMIT 1"
                ),
                (case,),
            ).fetchone()
            if body.expected_submission_id != (latest[0] if latest else None):
                fail(409, "stale_submission", "The current submission changed.")
            if not existing:
                insert(c, "cases", case_id=case, project_id=project, **reference, created_at=now())
                event(c, project, p.actor_id, "case.created", reference, case=case)
            sid = uid("sub")
            insert(
                c,
                "submissions",
                submission_id=sid,
                project_id=project,
                case_id=case,
                revision=latest[1] + 1 if latest else 1,
                host_revision=body.host_revision,
                work_type=body.work_type,
                summary=body.summary,
                action_type=body.proposed_action.type,
                action_json=dumps(body.proposed_action),
                work_json=dumps(body.work),
                context_json=dumps(body.context),
                evidence_json=dumps(capture["evidence"]),
                content_hash="",
                submitted_by=p.actor_id,
                received_at=now(),
            )
            sub = one(c, "submissions", project, submission_id=sid)
            response = {
                k: sub[k]
                for k in (
                    "case_id",
                    "submission_id",
                    "revision",
                    "host_revision",
                    "content_hash",
                    "received_at",
                )
            }
            response["review_token"] = review(c, project, case, a)["review_token"]
            event(
                c,
                project,
                p.actor_id,
                "submission.received",
                {"submission_id": sid, "input_hash": input_hash, "response": response},
                case=case,
            )
            return 201, response

        return self.mutate(p, project, "submit", "submission.create", key, body, action)

    def assess(
        self, p: Principal, project: str, case: str, key: str, body: m.AssessmentRequest
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            current = review(c, project, case, a)
            check_review(current, body.expected_review_token)
            if "evaluate" not in current["allowed_actions"]:
                fail(403, "owner_required", "Reassessment after a decision requires an owner.")
            if body.submission_id != current["submission_id"]:
                fail(409, "stale_submission", "Only the current submission can be evaluated.")
            sub = one(c, "submissions", project, case_id=case, submission_id=body.submission_id)
            profile = one(
                c,
                "profile_versions",
                project,
                profile_id=body.profile_ref.id,
                version=body.profile_ref.version,
            )
            definition = m.Definition.model_validate(profile["definition"])
            validate_definition(definition)
            if (
                sub["work_type"] not in definition.scope.work_types
                or sub["action_type"] not in definition.scope.action_types
            ):
                fail(422, "profile_scope", "Profile does not apply to this work/action.")
            if (
                any(r.check.id == "semantic_review" for r in definition.requirements)
                and self.transport is None
            ):
                fail(
                    422,
                    "interpreter_unavailable",
                    "This profile requires configured OpenAI interpretation.",
                )
            if (
                c.execute("SELECT COUNT(*) FROM assessments WHERE status='pending'").fetchone()[0]
                >= 16
            ):
                fail(
                    429, "queue_full", "Evaluation capacity is full. Retry later with the same key."
                )
            aid, stamp = uid("assessment"), now()
            insert(
                c,
                "assessments",
                assessment_id=aid,
                project_id=project,
                case_id=case,
                submission_id=body.submission_id,
                profile_id=body.profile_ref.id,
                profile_version=body.profile_ref.version,
                request_key=k,
                status="pending",
                evaluator_version=EVALUATOR_VERSION,
                evaluation_time=stamp,
                requested_at=stamp,
                run_json=dumps({"model": self.model, "requested_by": p.actor_id}),
            )
            event(
                c,
                project,
                p.actor_id,
                "assessment.requested",
                {
                    "submission_id": sub["submission_id"],
                    "input_hash": sub["content_hash"],
                    "profile_hash": profile["content_hash"],
                },
                case=case,
                assessment=aid,
            )
            return 202, {
                "assessment_id": aid,
                "status": "pending",
                "status_url": f"/api/v1/projects/{project}/cases/{case}/assessments/{aid}",
            }

        return self.mutate(
            p, project, "evaluate", f"assessment.create/{case}", key, body, action, case
        )

    def decide(
        self, p: Principal, project: str, case: str, key: str, body: m.DecisionRequest
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            current = review(c, project, case, a)
            check_review(current, body.expected_review_token)
            if (
                current["assessment_id"] != body.assessment_id
                or current["evaluation_status"] != "completed"
            ):
                fail(409, "assessment_not_current", "A current completed assessment is required.")
            previous = current["current_decision"]
            if previous and a["role"] != "owner":
                fail(403, "owner_required", "Replacing a decision requires an owner.")
            if body.supersedes_decision_id != (previous["decision_id"] if previous else None):
                fail(409, "stale_decision", "Name the current decision as predecessor.")
            assessment = one(c, "assessments", project, assessment_id=body.assessment_id)
            profile = one(
                c,
                "profile_versions",
                project,
                profile_id=assessment["profile_id"],
                version=assessment["profile_version"],
            )
            expiry = None
            if body.answer == "yes":
                exceptions = {e.requirement_id: e for e in body.exceptions}
                reqs = {r["id"]: r for r in profile["definition"]["requirements"]}
                blocked = {
                    r["requirement_id"]: r
                    for r in assessment["result"]["requirement_results"]
                    if r["status"] in ("unmet", "unknown")
                }
                if set(exceptions) != set(blocked):
                    fail(
                        422,
                        "requirements_unresolved",
                        "Every unresolved requirement needs an explicitly permitted exception.",
                    )
                for rid, result in blocked.items():
                    if (
                        a["role"] != "owner"
                        or result["status"] not in reqs[rid]["exception"]["allowed_statuses"]
                    ):
                        fail(
                            422,
                            "exception_forbidden",
                            "A requirement cannot be waived by this decision.",
                        )
                # No can always be recorded; expired assessment support cannot authorize a new Yes.
                deadline = datetime.fromisoformat(assessment["result"]["valid_until"])
                deadline = min(
                    deadline,
                    datetime.fromisoformat(now())
                    + timedelta(
                        seconds=profile["definition"]["review_rules"]["decision_max_age_seconds"]
                    ),
                )
                if body.valid_until:
                    if body.valid_until > deadline:
                        fail(
                            422,
                            "invalid_expiry",
                            "Requested validity exceeds the evidence/profile limit.",
                        )
                    deadline = body.valid_until
                if deadline <= datetime.fromisoformat(now()):
                    fail(422, "expired_support", "Reassess with current evidence before approving.")
                expiry = deadline.isoformat()
                case_row = one(c, "cases", project, case_id=case)
                # Host support comes from owner-managed metadata, not the decision.
                support = (
                    one(c, "projects", project)["metadata"]
                    .get("host_checks", {})
                    .get(case_row["host_id"], [])
                )
                for condition in body.conditions:
                    if (
                        condition.type
                        not in profile["definition"]["review_rules"]["permitted_condition_types"]
                        or set(condition.parameters) != {"check_id"}
                        or condition.parameters["check_id"] not in support
                    ):
                        fail(
                            422,
                            "unsupported_condition",
                            "The profile and host must support each named condition.",
                        )
            did = uid("decision")
            authority = {
                "project_id": project,
                "role": a["role"],
                "membership_version": a["version"],
                "permission": "replace_decision" if previous else "decide",
                "exceptions": [e.model_dump(mode="json") for e in body.exceptions],
                "submission_id": current["submission_id"],
                "submission_hash": current["submission_hash"],
                "assessment_hash": assessment["result_hash"],
                "profile_ref": current["profile_ref"],
                "profile_hash": profile["content_hash"],
            }
            insert(
                c,
                "decisions",
                decision_id=did,
                project_id=project,
                case_id=case,
                assessment_id=body.assessment_id,
                request_key=k,
                kind="decision",
                answer=body.answer,
                rationale=body.rationale,
                actor_id=p.actor_id,
                authority_json=dumps(authority),
                conditions_json=dumps(body.conditions),
                supersedes_decision_id=body.supersedes_decision_id,
                recorded_at=now(),
                valid_until=expiry,
                content_hash="",
            )
            event(
                c,
                project,
                p.actor_id,
                "decision.recorded",
                {"supersedes_decision_id": body.supersedes_decision_id},
                case=case,
                assessment=body.assessment_id,
                decision=did,
            )
            return 201, one(c, "decisions", project, decision_id=did)

        return self.mutate(p, project, "decide", f"decision.create/{case}", key, body, action, case)

    def revoke(
        self, p: Principal, project: str, case: str, decision: str, key: str, body: m.Revocation
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            current = review(c, project, case, a)
            check_review(current, body.expected_review_token)
            previous = current["current_decision"]
            if (
                not previous
                or previous["decision_id"] != decision
                or previous["kind"] != "decision"
            ):
                fail(409, "stale_decision", "Only the current decision can be revoked.")
            did = uid("revocation")
            insert(
                c,
                "decisions",
                decision_id=did,
                project_id=project,
                case_id=case,
                assessment_id=previous["assessment_id"],
                request_key=k,
                kind="revocation",
                answer=None,
                rationale=body.rationale,
                actor_id=p.actor_id,
                authority_json=dumps(
                    {
                        **previous["authority"],
                        "role": a["role"],
                        "membership_version": a["version"],
                        "permission": "revoke",
                        "exceptions": [],
                    }
                ),
                conditions_json="[]",
                supersedes_decision_id=decision,
                recorded_at=now(),
                valid_until=None,
                content_hash="",
            )
            event(
                c,
                project,
                p.actor_id,
                "decision.revoked",
                {"supersedes_decision_id": decision},
                case=case,
                assessment=previous["assessment_id"],
                decision=did,
            )
            return 201, one(c, "decisions", project, decision_id=did)

        return self.mutate(
            p, project, "owner", f"decision.revoke/{case}/{decision}", key, body, action, case
        )

    def concern(
        self, p: Principal, project: str, key: str, body: m.Concern
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            if body.assessment_id:
                assessment = one(
                    c,
                    "assessments",
                    project,
                    case_id=body.case_id,
                    assessment_id=body.assessment_id,
                )
                if body.finding_id and body.finding_id not in {
                    f["id"] for f in (assessment.get("result") or {}).get("findings", [])
                }:
                    fail(422, "invalid_finding", "Finding is not in this assessment.")
            if body.profile_ref:
                one(
                    c,
                    "profile_versions",
                    project,
                    profile_id=body.profile_ref.id,
                    version=body.profile_ref.version,
                )
            eid = event(
                c,
                project,
                p.actor_id,
                "concern.raised",
                body.model_dump(mode="json"),
                case=body.case_id,
                assessment=body.assessment_id,
                profile=body.profile_ref.id if body.profile_ref else None,
                version=body.profile_ref.version if body.profile_ref else None,
            )
            return 201, {"concern_id": eid, "version": 1, "resolved": False}

        return self.mutate(p, project, "concern", "concern.create", key, body, action, body.case_id)

    def respond(
        self, p: Principal, project: str, concern: str, key: str, body: m.ConcernResponse
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            original = one(c, "events", project, event_id=concern, event_type="concern.raised")
            check_version(
                version(c, project, "concern.responded", concern), body.expected_concern_version
            )
            if body.resolve:
                access(c, p, project, "resolve" if original["case_id"] else "owner")
            if body.corrective_submission_id:
                if not original["case_id"]:
                    fail(
                        422, "invalid_correction", "Submission correction requires a case concern."
                    )
                one(
                    c,
                    "submissions",
                    project,
                    case_id=original["case_id"],
                    submission_id=body.corrective_submission_id,
                )
            if body.corrective_assessment_id:
                if not original["case_id"]:
                    fail(
                        422, "invalid_correction", "Assessment correction requires a case concern."
                    )
                one(
                    c,
                    "assessments",
                    project,
                    case_id=original["case_id"],
                    assessment_id=body.corrective_assessment_id,
                )
            if body.corrective_profile_ref:
                one(
                    c,
                    "profile_versions",
                    project,
                    profile_id=body.corrective_profile_ref.id,
                    version=body.corrective_profile_ref.version,
                )
            eid = event(
                c,
                project,
                p.actor_id,
                "concern.responded",
                body.model_dump(mode="json"),
                case=original["case_id"],
                profile=original["profile_id"],
                version=original["profile_version"],
                related=concern,
            )
            return 201, {
                "event_id": eid,
                "concern_id": concern,
                "version": body.expected_concern_version + 1,
            }

        return self.mutate(p, project, "concern", f"concern.respond/{concern}", key, body, action)

    def report(
        self, p: Principal, project: str, case: str, key: str, body: m.HostReport
    ) -> tuple[int, dict[str, Any]]:
        def action(c: sqlite3.Connection, a: dict[str, Any], k: str) -> tuple[int, dict[str, Any]]:
            decision = one(c, "decisions", project, case_id=case, decision_id=body.decision_id)
            if datetime.fromisoformat(now()) < body.occurred_at:
                fail(422, "future_report", "Reported occurrence cannot be in the future.")
            if body.type == "execution_reported":
                required = {"host_action_id", "host_revision", "proposed_action", "status"}
                if (
                    set(body.details) != required
                    or body.details["status"] not in ("succeeded", "failed", "not_performed")
                    or any(
                        not isinstance(body.details[k], str) or not body.details[k].strip()
                        for k in ("host_action_id", "host_revision")
                    )
                ):
                    fail(
                        422,
                        "invalid_report",
                        "Execution report needs action identity, revision and status.",
                    )
                m.Action.model_validate(body.details["proposed_action"])
            elif body.type == "outcome_reported":
                if (
                    not all(
                        isinstance(body.details.get(k), str) and body.details[k].strip()
                        for k in ("measure", "scope", "units")
                    )
                    or "value" not in body.details
                ):
                    fail(422, "invalid_report", "An outcome needs measure, value, units and scope.")
            elif set(body.details) - {"message"}:
                fail(422, "invalid_report", "Acknowledgement permits only a message.")
            if body.corrects_event_id:
                previous = one(
                    c,
                    "events",
                    project,
                    case_id=case,
                    event_id=body.corrects_event_id,
                    event_type="host." + body.type,
                )
                if (
                    previous["actor_id"] != p.actor_id
                    or previous["decision_id"] != body.decision_id
                ):
                    fail(
                        422,
                        "invalid_correction",
                        "Correction must name this source's same-decision report.",
                    )
            current = review(c, project, case, a)
            matches = (
                current["current_decision"]
                and current["current_decision"]["decision_id"] == decision["decision_id"]
                and current["state"] in ("approved", "approved_with_conditions")
            )
            if body.type == "execution_reported":
                matches = (
                    matches
                    and body.details["host_revision"] == current["host_revision"]
                    and body.details["proposed_action"] == current["proposed_action"]
                )
            eid = event(
                c,
                project,
                p.actor_id,
                "host." + body.type,
                {**body.model_dump(mode="json"), "matches_current_authorization": bool(matches)},
                case=case,
                decision=body.decision_id,
                related=body.corrects_event_id,
                occurred_at=body.occurred_at.isoformat(),
            )
            return 201, one(c, "events", project, event_id=eid)

        return self.mutate(p, project, "report", f"host.report/{case}", key, body, action, case)

    def recover(self) -> int:
        with self.store.transaction(write=True) as c:
            rows = c.execute("SELECT * FROM assessments WHERE status='pending'").fetchall()
            for row in rows:
                self._finish(
                    c,
                    dict(row),
                    None,
                    {"recovery": True},
                    {
                        "code": "interrupted",
                        "message": "Service stopped before completion. Request a new assessment.",
                    },
                )
            return len(rows)

    def _finish(
        self,
        c: sqlite3.Connection,
        assessment: dict[str, Any],
        result: dict[str, Any] | None,
        run: dict[str, Any],
        error: dict[str, Any] | None,
    ) -> None:
        status = "completed" if result else "failed"
        changed = c.execute(
            (
                "UPDATE assessments SET "
                "status=?,finished_at=?,recommendation=?,result_json=?,result_hash=?,run_json=?,error_json=?"
                " WHERE assessment_id=? AND status='pending'"
            ),
            (
                status,
                now(),
                result["recommendation"]["answer"] if result else None,
                dumps(result) if result else None,
                digest(result) if result else None,
                dumps(run),
                dumps(error) if error else None,
                assessment["assessment_id"],
            ),
        ).rowcount
        if changed:
            event(
                c,
                assessment["project_id"],
                "reviewpoint:evaluator",
                "assessment." + status,
                {"error": error},
                case=assessment["case_id"],
                assessment=assessment["assessment_id"],
            )

    def process_one(self) -> bool:
        with self.store.transaction() as c:
            row = c.execute(
                "SELECT * FROM assessments WHERE status='pending' ORDER BY assessment_seq LIMIT 1"
            ).fetchone()
            if not row:
                return False
            assessment = unpack(row)
            sub = one(
                c,
                "submissions",
                assessment["project_id"],
                submission_id=assessment["submission_id"],
            )
            profile = one(
                c,
                "profile_versions",
                assessment["project_id"],
                profile_id=assessment["profile_id"],
                version=assessment["profile_version"],
            )
        result, error = None, None
        run = assessment["run"]
        try:
            result, details = evaluate(
                sub,
                profile["definition"],
                assessment["evaluation_time"],
                self.transport,
                run["model"],
            )
            run.update(details)
        except Exception as exc:
            if isinstance(exc, EvaluationFailure):
                run.update(exc.run)
            # Exception text may contain provider/input data; retain only a safe classification.
            error = {
                "code": "evaluation_failed",
                "message": "Evaluation did not produce a validated result.",
                "type": type(exc).__name__,
            }
        with self.store.transaction(write=True) as c:
            self._finish(c, assessment, result, run, error)
        return True
