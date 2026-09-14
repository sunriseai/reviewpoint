"""Trusted demo identity adapter and project authorization; no user directory."""

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

from .storage import dumps


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    kind: Literal["human", "integration"] = "human"
    grants: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def actor_id(self) -> str:
        return dumps([self.kind, self.issuer, self.subject])


class DemoIdentity:
    def __init__(self, principals: dict[str, Principal]):
        self.principals = principals  # SHA-256(token) -> trusted principal

    def authenticate(self, token: str) -> Principal:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        for expected, principal in self.principals.items():
            if hmac.compare_digest(hashed, expected):
                return principal
        raise ServiceError(401, "unauthenticated", "A valid demo credential is required.")


def access(
    c: sqlite3.Connection, p: Principal, project: str, capability: str = "read"
) -> dict[str, Any]:
    if not c.execute("SELECT 1 FROM projects WHERE project_id=?", (project,)).fetchone():
        raise ServiceError(404, "not_found", "Project or resource not found.")
    if p.kind == "integration":
        grant = p.grants.get(project, {})
        if "read" not in grant.get("capabilities", []):
            raise ServiceError(404, "not_found", "Project or resource not found.")
        if capability not in grant["capabilities"]:
            raise ServiceError(403, "forbidden", "This integration cannot perform this operation.")
        return {"role": "integration", "version": 1, **grant}
    row = c.execute(
        "SELECT * FROM project_memberships WHERE project_id=? AND actor_id=? AND active=1",
        (project, p.actor_id),
    ).fetchone()
    if row is None:
        raise ServiceError(404, "not_found", "Project or resource not found.")
    permissions = {
        "reviewer": {"read", "concern"},
        "approver": {"read", "concern", "decide", "evaluate", "resolve"},
        "owner": {"read", "concern", "decide", "evaluate", "resolve", "owner"},
    }
    if capability not in permissions[row["role"]]:
        raise ServiceError(403, "forbidden", "Your project role cannot perform this operation.")
    return dict(row)


def host_access(p: Principal, project: str, case: dict[str, Any]) -> None:
    if p.kind != "integration":
        return
    grant = p.grants.get(project, {})
    if case["host_id"] != grant.get("host_id") or case["workflow_id"] not in grant.get(
        "workflow_ids", []
    ):
        raise ServiceError(404, "not_found", "Project or resource not found.")
