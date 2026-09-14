"""One synthetic work review. Bootstrap never replaces an existing workspace."""

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from .identity import DemoIdentity, Principal
from .models import PublishProfile, Submission
from .openai_transport import OpenAITransport
from .service import Service
from .storage import Store, dumps, event, insert, now

PROJECT = "example"
HOST = "example-host"
ISSUER = "reviewpoint-local-demo"
FIELDS = [
    {"pointer": "/work/summary", "label": "Work summary", "type": "text"},
    {"pointer": "/work/expected_items", "label": "Expected items", "type": "number"},
    {"pointer": "/work/supplied_items", "label": "Supplied items", "type": "number"},
]


def profile(owner: str) -> PublishProfile:
    return PublishProfile.model_validate(
        {
            "name": "Work release guidelines",
            "owner_id": owner,
            "reason": "Initial illustrative guidelines for synthetic work",
            "definition": {
                "scope": {"work_types": ["work_item"], "action_types": ["release_work"]},
                "risks": [
                    {
                        "id": "incomplete",
                        "title": "Incomplete work",
                        "consequence": "Incomplete work reaches the next step",
                        "applies_to": "proceed",
                    },
                    {
                        "id": "rework",
                        "title": "Additional rework",
                        "consequence": "Additional effort to correct released work",
                        "applies_to": "proceed",
                    },
                    {
                        "id": "delay",
                        "title": "Processing delay",
                        "consequence": "The next step waits for a correction",
                        "applies_to": "hold",
                    },
                ],
                "requirements": [
                    {
                        "id": "summary",
                        "description": "The work has a summary",
                        "risk_ids": ["incomplete"],
                        "check": {
                            "id": "required_values",
                            "parameters": {"pointers": ["/work/summary"]},
                        },
                    },
                    {
                        "id": "complete",
                        "description": "All expected items are supplied",
                        "risk_ids": ["incomplete", "rework"],
                        "check": {
                            "id": "equal_values",
                            "parameters": {
                                "left": "/work/expected_items",
                                "right": "/work/supplied_items",
                            },
                        },
                    },
                ],
            },
        }
    )


def submission(
    work: dict[str, Any] | None = None, *, previous: str | None = None, revision: int = 1
) -> Submission:
    work = (
        work
        if work is not None
        else {
            "summary": "A work package ready for its next step",
            "expected_items": 4,
            "supplied_items": 3,
        }
    )
    return Submission.model_validate(
        {
            "case_ref": {
                "host_id": HOST,
                "workflow_id": "work-review",
                "external_case_id": "WORK-001",
                "checkpoint_key": "release",
            },
            "expected_submission_id": previous,
            "host_revision": f"revision-{revision}",
            "work_type": "work_item",
            "summary": "WORK-001 · Work release",
            "proposed_action": {
                "type": "release_work",
                "label": "Release this work to the next step.",
                "target": "simulated-next-step",
                "parameters": {},
            },
            "work": work,
            "context": {"source": "Synthetic example host; no real work is executed"},
            "evidence": [
                {
                    "id": "source",
                    "title": "Supplied work snapshot",
                    "media_type": "application/json",
                    "source_uri": "example:WORK-001",
                    "captured_at": now(),
                    "content": dumps(work),
                }
            ],
        }
    )


def seed(path: Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    store = Store(path / "reviewpoint.sqlite3")
    store.initialize()
    people = {role: Principal(ISSUER, role) for role in ("owner", "approver", "reviewer")}
    people["host"] = Principal(
        ISSUER,
        HOST,
        "integration",
        {
            PROJECT: {
                "capabilities": ["read", "submit", "evaluate", "report"],
                "host_id": HOST,
                "workflow_ids": ["work-review"],
            }
        },
    )
    tokens = {name: secrets.token_urlsafe(32) for name in people}
    config = {
        "authentication": "simulated_external_identity",
        "model": None,
        "principals": {
            hashlib.sha256(tokens[name].encode()).hexdigest(): {
                "issuer": p.issuer,
                "subject": p.subject,
                "kind": p.kind,
                "grants": p.grants,
            }
            for name, p in people.items()
        },
    }
    with store.transaction(write=True) as c:
        insert(
            c,
            "projects",
            project_id=PROJECT,
            project_key=PROJECT,
            name="Example workspace",
            metadata_json=dumps({"description": "Synthetic work review", "repositories": []}),
            created_by=people["owner"].actor_id,
            created_at=now(),
        )
        event(c, PROJECT, people["owner"].actor_id, "project.created", {"example": True})
        for role in ("owner", "approver", "reviewer"):
            insert(
                c,
                "project_memberships",
                project_id=PROJECT,
                actor_id=people[role].actor_id,
                role=role,
                active=1,
                version=1,
                changed_by=people["owner"].actor_id,
                changed_at=now(),
            )
            event(
                c,
                PROJECT,
                people["owner"].actor_id,
                "membership.created",
                {"actor_id": people[role].actor_id, "role": role},
            )
    saved = Service(store).publish(
        people["owner"], PROJECT, "bootstrap", profile(people["owner"].actor_id)
    )[1]
    for name, value in (
        ("config.json", config),
        ("demo-credentials.json", tokens),
        ("demo-profile.json", {"id": saved["profile_id"], "version": saved["version"]}),
    ):
        file = path / name
        file.write_text(dumps(value) + "\n")
        file.chmod(0o600)
    return {"workspace": str(path), "credentials_file": str(path / "demo-credentials.json")}


def load(path: Path, *, live: bool = False) -> tuple[Service, DemoIdentity]:
    config = json.loads((path / "config.json").read_text())
    model = config.get("model")
    if live and not model:
        raise ValueError(
            "Set model in the private workspace config before enabling live evaluation."
        )
    store = Store(path / "reviewpoint.sqlite3")
    store.initialize()
    identity = DemoIdentity(
        {key: Principal(**value) for key, value in config["principals"].items()}
    )
    return Service(store, OpenAITransport() if live else None, model or "not-configured"), identity


def prepare(path: Path) -> str:
    """Resume WORK-001 or submit it once through HTTP. Never make a human decision."""
    import asyncio

    import httpx

    from .app import create_app

    service, identity = load(path)
    tokens = json.loads((path / "demo-credentials.json").read_text())
    headers = {"Authorization": "Bearer " + tokens["host"], "Idempotency-Key": "initial-submission"}
    base = f"/api/v1/projects/{PROJECT}"

    async def run() -> str:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(service, identity, worker=False)),
            base_url="http://testserver",
        ) as client:
            response = await client.get(base + "/cases", headers=headers)
            response.raise_for_status()
            for case in response.json()["items"]:
                if case["external_case_id"] == "WORK-001":
                    return str(case["case_id"])
            response = await client.post(
                base + "/submissions", headers=headers, json=submission().model_dump(mode="json")
            )
            response.raise_for_status()
            receipt = response.json()
            response = await client.post(
                base + "/cases/" + receipt["case_id"] + "/assessments",
                headers={**headers, "Idempotency-Key": "initial-evaluation"},
                json={
                    "submission_id": receipt["submission_id"],
                    "profile_ref": json.loads((path / "demo-profile.json").read_text()),
                    "expected_review_token": receipt["review_token"],
                },
            )
            response.raise_for_status()
            service.process_one()
            return str(receipt["case_id"])

    with service.store.server_lock():
        return asyncio.run(run())
