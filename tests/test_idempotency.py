"""Mutation keys share one wire/service contract and retain replay identity."""

import pytest

from reviewpoint import models as m
from reviewpoint.identity import ServiceError
from tests.test_service import service_demo  # noqa: F401


@pytest.mark.parametrize("length", [None, 0, 1, 200, 201, 256, 257])
def test_key_limits_at_http_and_service_boundaries(service_demo, length):  # noqa: F811
    h = service_demo
    key = None if length is None else "k" * length
    body = m.ProjectEdit(expected_version=1, name="Updated work", reason="Synthetic update")
    principal = h.identity.authenticate(h.tokens["owner"])
    valid = length is not None and 1 <= length <= 256
    before = h.service.store.verify()["events"]
    if valid:
        result = h.service.project_edit(principal, "work", key, body)
        assert result[0] == 200
    else:
        with pytest.raises(ServiceError) as exc:
            h.service.project_edit(principal, "work", key, body)
        assert exc.value.status == 400
        assert exc.value.code == "invalid_request_key"
    headers = {"Authorization": "Bearer " + h.tokens["owner"]}
    if key is not None:
        headers["Idempotency-Key"] = key
    response = h.client.patch(
        "/api/v1/projects/work", json=body.model_dump(mode="json"), headers=headers
    )
    assert response.status_code == (200 if valid else 400)
    if valid:
        assert response.json() == result[1]
        changed = h.client.patch(
            "/api/v1/projects/work",
            headers=headers,
            json={**body.model_dump(mode="json"), "name": "Other"},
        )
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "idempotency_conflict"
    else:
        assert response.json()["error"]["code"] == "invalid_request_key"
        assert h.service.store.verify()["events"] == before
