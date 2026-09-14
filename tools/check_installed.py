"""Smoke-test an installed wheel from a fresh environment, without Node or provider calls."""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

import reviewpoint
from reviewpoint.app import create_app
from reviewpoint.demo import load


def check() -> None:
    package = Path(reviewpoint.__file__).resolve().parent
    if "site-packages" not in package.parts:
        raise SystemExit(
            "Run this check with a fresh wheel installation, not an editable checkout."
        )
    env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "PYTHONPATH"}}
    env["PATH"] = str(Path(sys.executable).parent)
    with TemporaryDirectory(prefix="reviewpoint-wheel-") as temporary:
        workspace = Path(temporary) / "workspace"
        for args in (
            ["demo", "--prepare-only"],
            ["demo", "--prepare-only"],
            ["verify"],
            ["backup", str(Path(temporary) / "backup.sqlite3")],
        ):
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from reviewpoint.cli import app; app()",
                    *args,
                    "--workspace",
                    str(workspace),
                ],
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise SystemExit(f"Installed CLI check failed: {args[0]}\n{result.stderr}")
        service, identity = load(workspace)
        credentials = json.loads((workspace / "demo-credentials.json").read_text())

        async def exercise() -> None:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(service, identity, worker=False)),
                base_url="http://testserver",
            ) as client:
                assert (await client.get("/api/v1/projects")).status_code == 401
                response = await client.get(
                    "/api/v1/projects", headers={"Authorization": "Bearer " + credentials["owner"]}
                )
                assert response.status_code == 200 and response.json()["items"]
                for path in ("/", "/docs"):
                    response = await client.get(path)
                    assert response.status_code == 200
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text)
                    assert assets
                    for asset in assets:
                        assert (await client.get(asset)).status_code == 200, asset
                assert (await client.get("/openapi.json")).status_code == 200
                for name in ("LICENSE.txt", "NOTICE.txt", "swagger-ui-bundle.js.LICENSE.txt"):
                    assert (await client.get("/assets/swagger/" + name)).status_code == 200

        asyncio.run(exercise())
    print("Installed wheel passed: offline CLI/resume/verify/backup, authenticated API and assets.")


if __name__ == "__main__":
    check()
