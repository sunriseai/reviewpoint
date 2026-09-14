"""SQLite unit of work; all service transitions use short serialized writes."""

import fcntl
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from reviewpoint.canonical import canonical_bytes, digest


def now() -> str:
    return datetime.now(UTC).isoformat()


def uid(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


def dumps(value: Any) -> str:
    return canonical_bytes(TypeAdapter(Any).dump_python(value, mode="json")).decode()


def unpack(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        k.removesuffix("_json"): json.loads(v) if k.endswith("_json") and v is not None else v
        for k, v in dict(row).items()
    }


def row_hash(row: dict[str, Any]) -> str:
    return digest({k: v for k, v in row.items() if k != "content_hash" and not k.endswith("_seq")})


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self.connect()) as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported service database version")
            if version == 0:
                if c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("refusing to migrate an unversioned nonempty database")
                c.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + Path(__file__).with_name("migration.sql").read_text()
                    + "\nPRAGMA user_version=1;\nCOMMIT;"
                )
            c.execute("PRAGMA journal_mode=WAL")
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @contextmanager
    def server_lock(self) -> Iterator[None]:
        with self.path.with_suffix(".server.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another service process owns this database") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def verify(self) -> dict[str, Any]:
        with self.transaction() as c:
            if (
                c.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or c.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("database integrity verification failed")
            counts = {}
            for table in (
                "projects",
                "project_memberships",
                "profile_versions",
                "cases",
                "submissions",
                "assessments",
                "decisions",
                "events",
            ):
                rows = c.execute(f"SELECT * FROM {table}").fetchall()
                counts[table] = len(rows)
                if table in ("profile_versions", "submissions", "decisions"):
                    for row in rows:
                        if row["content_hash"] != row_hash(dict(row)):
                            raise ValueError(f"content hash mismatch in {table}")
                if table == "assessments":
                    for row in rows:
                        if (
                            row["status"] == "completed"
                            and digest(json.loads(row["result_json"])) != row["result_hash"]
                        ):
                            raise ValueError("assessment result hash mismatch")
            return counts

    def backup(self, target: Path) -> None:
        with target.open("xb"):
            pass
        target.chmod(0o600)
        with closing(self.connect()) as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)


def insert(c: sqlite3.Connection, table: str, **values: Any) -> None:
    # Table/column names originate only from service code, never client input.
    if "content_hash" in values:
        values["content_hash"] = row_hash(values)
    c.execute(
        f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
        tuple(values.values()),
    )


def event(
    c: sqlite3.Connection,
    project: str,
    actor: str,
    kind: str,
    payload: Any,
    *,
    case: str | None = None,
    profile: str | None = None,
    version: int | None = None,
    assessment: str | None = None,
    decision: str | None = None,
    related: str | None = None,
    occurred_at: str | None = None,
    source_key: str | None = None,
) -> str:
    eid = uid("evt")
    insert(
        c,
        "events",
        event_id=eid,
        project_id=project,
        case_id=case,
        profile_id=profile,
        profile_version=version,
        assessment_id=assessment,
        decision_id=decision,
        related_event_id=related,
        source_id=actor,
        source_event_key=source_key or eid,
        event_type=kind,
        actor_id=actor,
        recorded_at=now(),
        occurred_at=occurred_at,
        payload_json=dumps(payload),
    )
    return eid
