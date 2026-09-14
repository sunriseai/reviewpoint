"""Optional example-host bridge. Calls the public API with its integration identity.

Installed only by `reviewpoint demo`. Humans authenticate normally; no integration
credential is exposed to the browser. This demonstrates a host, not a workflow engine.
"""

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime

from .demo import FIELDS, HOST, PROJECT
from .identity import DemoIdentity, Principal, ServiceError, access
from .models import ID, Model, Submission
from .service import Service


class Handoff(Model):
    submission_id: ID
    decision_id: ID
    occurred_at: AwareDatetime


def attach(
    app: FastAPI, service: Service, identity: DemoIdentity, workspace: Path, case_id: str
) -> None:
    token = json.loads((workspace / "demo-credentials.json").read_text())["host"]
    base = f"/api/v1/projects/{PROJECT}"
    case = base + "/cases/" + case_id

    def human(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise ServiceError(401, "unauthenticated", "Supply a demo bearer credential.")
        p = identity.authenticate(authorization[7:])
        if p.kind != "human":
            raise ServiceError(403, "human_required", "Sign in with a human demo identity.")
        with service.store.transaction() as c:
            access(c, p, PROJECT)
        return p

    def editor(p: Annotated[Principal, Depends(human)]) -> Principal:
        with service.store.transaction() as c:
            access(c, p, PROJECT, "decide")
        return p

    async def call(method: str, path: str, body: Any = None, key: str | None = None) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.request(
                method,
                path,
                headers={
                    "Authorization": "Bearer " + token,
                    **({"Idempotency-Key": key} if key else {}),
                },
                json=body,
            )
            if r.is_error:
                detail = r.json()["error"]
                raise ServiceError(r.status_code, detail["code"], detail["message"])
            return r.json()

    @app.get("/example-host")
    async def info(p: Annotated[Principal, Depends(human)]) -> dict[str, Any]:
        return {"project_id": PROJECT, "case_id": case_id, "fields": FIELDS, "simulation": True}

    @app.post("/example-host/submissions")
    async def revise(
        body: Submission,
        p: Annotated[Principal, Depends(editor)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=256)],
    ) -> JSONResponse:
        expected = (HOST, "work-review", "WORK-001", "release")
        ref = body.case_ref
        if (ref.host_id, ref.workflow_id, ref.external_case_id, ref.checkpoint_key) != expected:
            raise ServiceError(422, "wrong_example", "This host panel only revises WORK-001.")
        result = await call(
            "POST", base + "/submissions", body.model_dump(mode="json"), idempotency_key
        )
        return JSONResponse(result, status_code=201)

    @app.post("/example-host/handoff")
    async def handoff(
        body: Handoff,
        p: Annotated[Principal, Depends(editor)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> Any:
        current = await call("GET", case + "/review")
        decision = current.get("current_decision")
        if (
            current["state"] != "approved"
            or current["submission_id"] != body.submission_id
            or not decision
            or decision["decision_id"] != body.decision_id
        ):
            raise ServiceError(
                409,
                "not_authorized",
                "The current work has no matching unconditional approval. Refresh the review.",
            )
        retained = await call("GET", current["evidence_url"])
        if (
            retained["action"] != current["proposed_action"]
            or retained["host_revision"] != current["host_revision"]
        ):
            raise ServiceError(409, "work_changed", "The proposed work or action changed.")
        # Stable event time/body makes repeated requests safe under the same idempotency key.
        timestamp = body.occurred_at.isoformat()
        await call(
            "POST",
            case + "/host-reports",
            {
                "decision_id": body.decision_id,
                "type": "acknowledged",
                "occurred_at": timestamp,
                "details": {
                    "message": "Example host retrieved the decision for a simulated handoff only",
                },
            },
            idempotency_key + ":ack",
        )
        return await call(
            "POST",
            case + "/host-reports",
            {
                "decision_id": body.decision_id,
                "type": "execution_reported",
                "occurred_at": timestamp,
                "details": {
                    "status": "succeeded",
                    "host_action_id": "simulation:" + body.decision_id + ":handoff",
                    "host_revision": retained["host_revision"],
                    "proposed_action": retained["action"],
                },
            },
            idempotency_key + ":execution",
        )
