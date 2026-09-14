"""HTTP adapter. All domain writes delegate to the transactional service."""

import base64
import json
import sqlite3
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import models as m
from .identity import DemoIdentity, Principal, ServiceError, access, host_access
from .service import Service, get_case, one, review, version
from .storage import dumps, uid, unpack


def create_app(service: Service, identity: DemoIdentity, *, worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not worker:
            yield
            return
        with service.store.server_lock():
            service.recover()
            stop = threading.Event()

            def run() -> None:
                while not stop.is_set():
                    try:
                        if not service.process_one():
                            stop.wait(0.2)
                    except sqlite3.OperationalError:
                        stop.wait(1)

            thread = threading.Thread(target=run, name="reviewpoint-evaluator", daemon=True)
            thread.start()
            try:
                yield
            finally:
                stop.set()
                thread.join(timeout=185)
                if thread.is_alive():
                    raise RuntimeError(
                        "evaluation worker did not stop; do not restart this process"
                    )

    app = FastAPI(
        title="Reviewpoint HITL service",
        version="1.0.0",
        lifespan=lifespan,
        description="Local service POC. External demo identity; host owns enforcement.",
        responses={
            code: {"model": m.ErrorResponse, "description": description}
            for code, description in {
                400: "Bad Request",
                401: "Unauthorized",
                403: "Forbidden",
                404: "Not Found",
                409: "Conflict",
                413: "Content Too Large",
                422: "Unprocessable Content",
                429: "Too Many Requests",
                503: "Service Unavailable",
            }.items()
        },
    )

    @app.middleware("http")
    async def boundaries(request: Request, call_next: Any) -> Any:
        request.state.request_id = uid("request")
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        if host not in ("127.0.0.1", "localhost", "testserver") or (
            origin and origin != f"http://{request.headers.get('host')}"
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "origin_forbidden",
                        "message": "Use the local service origin.",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=403,
            )
        if request.method in ("POST", "PUT", "PATCH"):
            parts, size = [], 0
            async for part in request.stream():
                size += len(part)
                if size > 5 * 1048576:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "input_too_large",
                                "message": "Request exceeds 5 MiB.",
                                "request_id": request.state.request_id,
                            }
                        },
                        status_code=413,
                    )
                parts.append(part)
            request._body = b"".join(parts)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request.state.request_id}},
            status_code=status,
            headers={"Retry-After": "2"} if status in (429, 503) else None,
        )

    @app.exception_handler(ServiceError)
    async def domain_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(
            request,
            400 if any(e["type"] == "json_invalid" for e in exc.errors()) else 422,
            "invalid_request",
            "Request does not match the service contract.",
        )

    @app.exception_handler(ValidationError)
    async def invalid_value(request: Request, exc: ValidationError) -> JSONResponse:
        return error(request, 422, "invalid_value", "Supplied values do not match the contract.")

    @app.exception_handler(sqlite3.IntegrityError)
    async def constraint(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        return error(
            request,
            409,
            "record_conflict",
            "The record conflicts with an existing record or scope.",
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def unavailable(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        return error(
            request, 503, "storage_unavailable", "Storage is unavailable. Retry with the same key."
        )

    def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise ServiceError(401, "unauthenticated", "Supply a demo bearer credential.")
        return identity.authenticate(authorization[7:])

    def request_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
        if not idempotency_key or len(idempotency_key) > 256:
            raise ServiceError(
                400, "request_key_required", "Idempotency-Key must contain 1–256 characters."
            )
        return idempotency_key

    prefix = "/api/v1/projects/{project}"

    def respond(result: tuple[int, dict[str, Any]]) -> JSONResponse:
        return JSONResponse(result[1], status_code=result[0])

    @app.get("/api/v1/projects", response_model=m.Page[m.ProjectSummary])
    def projects(
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            items = []
            for row in c.execute("SELECT * FROM projects ORDER BY rowid"):
                project = unpack(row)
                try:
                    authority = access(c, p, project["project_id"])
                except ServiceError:
                    continue
                items.append({**project, "role": authority["role"]})
            return page(items, limit, cursor, ["projects"])

    @app.get(prefix, response_model=m.ProjectDetail)
    def project_get(project: str, p: Annotated[Principal, Depends(principal)]) -> dict[str, Any]:
        with service.store.transaction() as c:
            authority = access(c, p, project)
            return {
                **one(c, "projects", project),
                "version": version(c, project, "project.changed"),
                "actor_id": p.actor_id,
                "role": authority["role"],
                "capabilities": authority.get("capabilities", []),
                "authentication": "simulated_external_identity",
                "limits": {
                    "request_bytes": 5 * 1048576,
                    "evidence_bytes": 1048576,
                    "evidence_items": 100,
                },
            }

    @app.patch(prefix, response_model=m.ProjectChanged)
    def project_patch(
        project: str,
        body: m.ProjectEdit,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.project_edit(p, project, key, body))

    @app.get(prefix + "/memberships", response_model=m.Page[m.MembershipRecord])
    def members(
        project: str,
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            access(c, p, project, "owner")
            rows = [
                unpack(r)
                for r in c.execute(
                    "SELECT * FROM project_memberships WHERE project_id=? ORDER BY rowid",
                    (project,),
                )
            ]
            return page(rows, limit, cursor, [project, "memberships"])

    @app.put(
        prefix + "/memberships",
        response_model=m.MembershipRecord,
        responses={201: {"model": m.MembershipRecord}},
    )
    def member_put(
        project: str,
        body: m.MembershipEdit,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.membership(p, project, key, body))

    @app.post(prefix + "/profiles", status_code=201, response_model=m.ProfileRecord)
    def profile_post(
        project: str,
        body: m.PublishProfile,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.publish(p, project, key, body))

    @app.post(
        prefix + "/profiles/{profile}/versions", status_code=201, response_model=m.ProfileRecord
    )
    def version_post(
        project: str,
        profile: str,
        body: m.PublishVersion,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.publish(p, project, key, body, profile))

    @app.get(prefix + "/profiles/{profile}/versions/{number}", response_model=m.ProfileRecord)
    def profile_get(
        project: str, profile: str, number: int, p: Annotated[Principal, Depends(principal)]
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            access(c, p, project)
            return one(c, "profile_versions", project, profile_id=profile, version=number)

    @app.post(
        prefix + "/submissions",
        status_code=201,
        response_model=m.SubmissionReceipt,
        responses={200: {"model": m.SubmissionReceipt}},
    )
    def submission_post(
        project: str,
        body: m.Submission,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.submit(p, project, key, body))

    @app.get(prefix + "/cases/{case}/review", response_model=m.Review)
    def review_get(
        project: str, case: str, p: Annotated[Principal, Depends(principal)]
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            authority = access(c, p, project)
            get_case(c, p, project, case)
            return review(c, project, case, authority)

    @app.post(
        prefix + "/cases/{case}/assessments", status_code=202, response_model=m.AssessmentReceipt
    )
    def assessment_post(
        project: str,
        case: str,
        body: m.AssessmentRequest,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.assess(p, project, case, key, body))

    @app.post(prefix + "/cases/{case}/decisions", status_code=201, response_model=m.DecisionRecord)
    def decision_post(
        project: str,
        case: str,
        body: m.DecisionRequest,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.decide(p, project, case, key, body))

    @app.post(
        prefix + "/cases/{case}/decisions/{decision}/revocations",
        status_code=201,
        response_model=m.DecisionRecord,
    )
    def revocation_post(
        project: str,
        case: str,
        decision: str,
        body: m.Revocation,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.revoke(p, project, case, decision, key, body))

    @app.post(prefix + "/concerns", status_code=201, response_model=m.ConcernReceipt)
    def concern_post(
        project: str,
        body: m.Concern,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.concern(p, project, key, body))

    @app.post(
        prefix + "/concerns/{concern}/responses", status_code=201, response_model=m.ResponseReceipt
    )
    def response_post(
        project: str,
        concern: str,
        body: m.ConcernResponse,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.respond(p, project, concern, key, body))

    @app.post(prefix + "/cases/{case}/host-reports", status_code=201, response_model=m.EventRecord)
    def report_post(
        project: str,
        case: str,
        body: m.HostReport,
        p: Annotated[Principal, Depends(principal)],
        key: Annotated[str, Depends(request_key)],
    ) -> JSONResponse:
        return respond(service.report(p, project, case, key, body))

    def public_record(table: str, row: dict[str, Any]) -> dict[str, Any]:
        if table != "assessments":
            return row
        run = row.get("run", {})
        visible = {
            "model",
            "response_id",
            "usage",
            "prompt_version",
            "schema_hash",
            "max_output_tokens",
            "request_hash",
            "validation_status",
            "error_type",
        }
        return {
            **row,
            "run": {
                **{k: run[k] for k in ("evaluator_version", "model", "requested_by") if k in run},
                "calls": [
                    {k: v for k, v in call.items() if k in visible} for call in run.get("calls", [])
                ],
            },
        }

    def record_route(table: str, identifier: str) -> None:
        def get(
            project: str, case: str, record: str, p: Annotated[Principal, Depends(principal)]
        ) -> dict[str, Any]:
            with service.store.transaction() as c:
                access(c, p, project)
                get_case(c, p, project, case)
                return public_record(
                    table, one(c, table, project, case_id=case, **{identifier: record})
                )

        app.get(
            prefix + f"/cases/{{case}}/{table}/{{record}}",
            response_model={
                "submissions": m.SubmissionRecord,
                "assessments": m.AssessmentRecord,
                "decisions": m.DecisionRecord,
            }[table],
            operation_id="get_" + table,
        )(get)

    for table, identifier in (
        ("submissions", "submission_id"),
        ("assessments", "assessment_id"),
        ("decisions", "decision_id"),
    ):
        record_route(table, identifier)

    def page(
        rows: list[dict[str, Any]],
        limit: int,
        cursor: str | None,
        scope: list[Any],
        *,
        events_after: int | None = None,
    ) -> dict[str, Any]:
        offset, bound = 0, len(rows)
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if (
                    decoded["scope"] != scope
                    or not isinstance(decoded["offset"], int)
                    or not isinstance(decoded["bound"], int)
                    or decoded["offset"] < 0
                    or decoded["bound"] < 0
                    or decoded["bound"] > len(rows)
                ):
                    raise ValueError
                offset, bound = decoded["offset"], decoded["bound"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ServiceError(
                    400, "invalid_cursor", "Cursor does not match this query."
                ) from exc
        items = rows[:bound][offset : offset + limit]
        next_cursor = (
            base64.urlsafe_b64encode(
                dumps({"scope": scope, "offset": offset + limit, "bound": bound}).encode()
            ).decode()
            if offset + limit < min(bound, len(rows))
            else None
        )
        result: dict[str, Any] = {"items": items, "next_cursor": next_cursor}
        if events_after is not None:
            result["upper_sequence"] = rows[bound - 1]["event_seq"] if bound else events_after
        return result

    @app.get(prefix + "/profiles", response_model=m.Page[m.ProfileRecord])
    def profiles(
        project: str,
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            access(c, p, project)
            rows = [
                unpack(r)
                for r in c.execute(
                    (
                        "SELECT p.* FROM profile_versions p WHERE project_id=? AND "
                        "version=(SELECT MAX(version) FROM profile_versions p2 WHERE "
                        "p2.project_id=p.project_id AND p2.profile_id=p.profile_id) ORDER "
                        "BY (SELECT MIN(rowid) FROM profile_versions p3 WHERE "
                        "p3.project_id=p.project_id AND p3.profile_id=p.profile_id)"
                    ),
                    (project,),
                )
            ]
            return page(rows, limit, cursor, [project, "profiles"])

    @app.get(prefix + "/profiles/{profile}/versions", response_model=m.Page[m.ProfileRecord])
    def versions(
        project: str,
        profile: str,
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            access(c, p, project)
            rows = [
                unpack(r)
                for r in c.execute(
                    (
                        "SELECT * FROM profile_versions WHERE project_id=? AND "
                        "profile_id=? ORDER BY version"
                    ),
                    (project, profile),
                )
            ]
            return page(rows, limit, cursor, [project, "versions", profile])

    @app.get(prefix + "/cases", response_model=m.Page[m.CaseSummary])
    def cases(
        project: str,
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
        host_id: str | None = None,
        workflow_id: str | None = None,
        external_case_id: str | None = None,
        checkpoint_key: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        filters = {
            "host_id": host_id,
            "workflow_id": workflow_id,
            "external_case_id": external_case_id,
            "checkpoint_key": checkpoint_key,
        }
        with service.store.transaction() as c:
            authority = access(c, p, project)
            rows = []
            for row in c.execute(
                "SELECT * FROM cases WHERE project_id=? ORDER BY rowid", (project,)
            ):
                item = unpack(row)
                try:
                    host_access(p, project, item)
                except ServiceError:
                    continue
                if any(v is not None and item[k] != v for k, v in filters.items()):
                    continue
                current = review(c, project, item["case_id"], authority)
                if state is None or current["state"] == state:
                    rows.append({**item, "state": current["state"], "summary": current["summary"]})
            return page(rows, limit, cursor, [project, "cases", filters, state])

    def list_route(table: str, order: str) -> None:
        def get(
            project: str,
            case: str,
            p: Annotated[Principal, Depends(principal)],
            limit: int = Query(25, ge=1, le=100),
            cursor: str | None = None,
        ) -> dict[str, Any]:
            with service.store.transaction() as c:
                access(c, p, project)
                get_case(c, p, project, case)
                rows = [
                    public_record(table, unpack(r))
                    for r in c.execute(
                        f"SELECT * FROM {table} WHERE project_id=? AND case_id=? ORDER BY {order}",
                        (project, case),
                    )
                ]
                return page(rows, limit, cursor, [project, case, table])

        app.get(
            prefix + f"/cases/{{case}}/{table}",
            response_model={
                "submissions": m.Page[m.SubmissionRecord],
                "assessments": m.Page[m.AssessmentRecord],
            }[table],
            operation_id="list_" + table,
        )(get)

    list_route("submissions", "revision")
    list_route("assessments", "assessment_seq")

    @app.get(prefix + "/events", response_model=m.EventPage)
    def events(
        project: str,
        p: Annotated[Principal, Depends(principal)],
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
        case_id: str | None = None,
        profile_id: str | None = None,
        after_sequence: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        with service.store.transaction() as c:
            authority = access(c, p, project)
            membership_visible = p.kind == "human" and authority["role"] == "owner"
            grant = p.grants.get(project, {}) if p.kind == "integration" else {}
            visibility = [
                p.actor_id,
                membership_visible,
                grant.get("host_id"),
                sorted(set(grant.get("workflow_ids", []))),
            ]
            if case_id:
                get_case(c, p, project, case_id)
            rows = []
            for row in c.execute(
                (
                    "SELECT * FROM events WHERE project_id=? AND event_seq>? AND "
                    "event_type!='request.completed' ORDER BY event_seq"
                ),
                (project, after_sequence),
            ):
                item = unpack(row)
                if item["event_type"].startswith("membership.") and not membership_visible:
                    continue
                if (
                    case_id
                    and item["case_id"] != case_id
                    or profile_id
                    and item["profile_id"] != profile_id
                ):
                    continue
                if item["case_id"]:
                    try:
                        get_case(c, p, project, item["case_id"])
                    except ServiceError:
                        continue
                rows.append(item)
            result = page(
                rows,
                limit,
                cursor,
                [project, "events", case_id, profile_id, after_sequence, visibility],
                events_after=after_sequence,
            )
            return result

    assets = Path(__file__).with_name("assets")
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(assets / "index.html")

    return app
