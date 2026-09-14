"""Local lifecycle commands. Demo actions are synthetic and never automatic approvals."""

import json
from pathlib import Path
from typing import Annotated

import typer

from .demo import load, prepare, seed
from .storage import Store

app = typer.Typer(no_args_is_help=True)
Workspace = Annotated[Path, typer.Option()]


@app.command()
def init(workspace: Workspace = Path(".workspace")) -> None:
    """Create a fresh database and private demonstration identities."""
    typer.echo(json.dumps(seed(workspace), indent=2))


@app.command()
def serve(workspace: Workspace = Path(".workspace"), port: int = 8767, live: bool = False) -> None:
    """Run the service only; --live enables explicitly configured paid semantic checks."""
    import uvicorn

    from .app import create_app

    service, identity = load(workspace, live=live)
    uvicorn.run(
        create_app(service, identity), host="127.0.0.1", port=port, workers=1, access_log=False
    )


@app.command()
def demo(
    workspace: Workspace = Path(".workspace"),
    port: int = 8767,
    prepare_only: bool = False,
    live: bool = False,
) -> None:
    """Resume one interactive work review, or prepare it without starting a server."""
    import uvicorn

    from .app import create_app
    from .example_host import attach

    if not workspace.exists():
        seed(workspace)
    case_id = prepare(workspace)
    typer.echo(
        f"WORK-001: {case_id}\nCredentials: {workspace / 'demo-credentials.json'}\n"
        "Sign in with the owner credential from that local file."
    )
    if prepare_only:
        return
    service, identity = load(workspace, live=live)
    application = create_app(service, identity)
    attach(application, service, identity, workspace, case_id)
    typer.echo(f"Open http://127.0.0.1:{port}/")
    uvicorn.run(application, host="127.0.0.1", port=port, workers=1, access_log=False)


@app.command()
def verify(workspace: Workspace = Path(".workspace")) -> None:
    """Check SQLite and retained record hashes; not independent proof of sound judgment."""
    typer.echo(json.dumps(Store(workspace / "reviewpoint.sqlite3").verify(), indent=2))


@app.command()
def backup(target: Path, workspace: Workspace = Path(".workspace")) -> None:
    """Back up the database to a new path; credentials remain separate."""
    Store(workspace / "reviewpoint.sqlite3").backup(target)
    typer.echo(str(target))


@app.command("export-contracts")
def export_contracts(directory: Path = Path("schemas"), check: bool = False) -> None:
    from .contracts import export

    typer.echo(f"{export(directory, check=check)} contracts {'match' if check else 'exported'}")
