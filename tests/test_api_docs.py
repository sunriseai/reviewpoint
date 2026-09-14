"""The packaged API documentation works without a CDN or permissive script policy."""

import re

from fastapi.testclient import TestClient

from reviewpoint.app import create_app
from reviewpoint.demo import load, seed


def test_docs_use_packaged_assets_and_scoped_policy(tmp_path):
    workspace = tmp_path / "workspace"
    seed(workspace)
    service, identity = load(workspace)
    with TestClient(create_app(service, identity, worker=False)) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', response.text)
        styles = re.findall(r'<link[^>]+href="([^"]+\.css)"', response.text)
        assert len(scripts) == 2 and len(styles) == 1
        assert "<script>" not in response.text
        for path in scripts + styles:
            assert path.startswith("/assets/swagger/")
            asset = client.get(path)
            assert asset.status_code == 200
            assert "sourceMappingURL=" not in asset.text
        for name in ("LICENSE.txt", "NOTICE.txt", "swagger-ui-bundle.js.LICENSE.txt"):
            assert client.get("/assets/swagger/" + name).status_code == 200
        policy = response.headers["content-security-policy"]
        assert "script-src 'self';" in policy
        assert "style-src-attr 'unsafe-inline'" in policy
        assert "img-src 'self' data:" in policy
        for path in ("/", "/openapi.json", scripts[0]):
            assert "unsafe-inline" not in client.get(path).headers["content-security-policy"]
        assert client.get("/redoc", follow_redirects=False).headers["location"] == "/docs"
        assert client.get("/docs/oauth2-redirect").status_code == 404
        spec = client.get("/openapi.json").json()
        assert spec["components"]["securitySchemes"]["BearerIdentity"] == {
            "type": "http",
            "scheme": "bearer",
        }
        assert spec["paths"]["/api/v1/projects"]["get"]["security"] == [{"BearerIdentity": []}]
        mutation = spec["paths"]["/api/v1/projects/{project}/submissions"]["post"]
        key = next(p for p in mutation["parameters"] if p["name"] == "idempotency-key")
        assert key["schema"]["minLength"] == 1
        assert key["schema"]["maxLength"] == 256
