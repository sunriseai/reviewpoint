"""Generate public service schemas from the same models used by HTTP."""

import json
from pathlib import Path

from pydantic import BaseModel

from . import models
from .app import create_app
from .identity import DemoIdentity
from .service import Service
from .storage import Store


def export(directory: Path, *, check: bool = False) -> int:
    artifacts = {}
    for name, model in vars(models).items():
        if (
            isinstance(model, type)
            and issubclass(model, BaseModel)
            and model.__module__ == models.__name__
            and name not in ("Model", "Page")
        ):
            artifacts[name + ".schema.json"] = model.model_json_schema()
    app = create_app(
        Service(Store(Path("unused-contract-export.sqlite"))), DemoIdentity({}), worker=False
    )
    artifacts["openapi.json"] = app.openapi()
    for filename, data in artifacts.items():
        content = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = directory / filename
        if check:
            if not path.exists() or path.read_text() != content:
                raise ValueError("service contract drift: " + filename)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return len(artifacts)
