"""Shared mutation-key validation and stable child-operation keys."""

from typing import Annotated

from fastapi import Header

from .canonical import digest
from .identity import ServiceError

MAX_KEY_LENGTH = 256


def validate_key(key: str | None) -> str:
    if not key or len(key) > MAX_KEY_LENGTH:
        raise ServiceError(
            400,
            "invalid_request_key",
            f"Idempotency-Key must contain 1–{MAX_KEY_LENGTH} characters.",
        )
    return key


def request_key(
    idempotency_key: Annotated[
        str | None,
        Header(json_schema_extra={"minLength": 1, "maxLength": MAX_KEY_LENGTH}),
    ] = None,
) -> str:
    # Validate explicitly so missing and invalid headers share the same HTTP 400 contract.
    return validate_key(idempotency_key)


def child_key(key: str, operation: str) -> str:
    validate_key(key)
    legacy = key + ":" + operation
    if len(legacy) <= MAX_KEY_LENGTH:
        return legacy
    return digest(["example-host-handoff", key, operation])
