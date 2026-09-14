"""Inspect publishable files. Known legacy identifiers are retained only as hashes."""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Hashes avoid reintroducing private identifiers into this public repository.
LEGACY_HASHES = {
    "4b83d4e48f471ac2bb7928f30d59d102276467cc0f3768ef57c1cf60b206d879",
    "49b5e39c84ac95ca92d5568b5ef6c7f065333ed8afca490121d2a8165741a01a",
    "cc0d4c4f3a05291e5da69d261a053756c8965d8ca3c95e9f7ae364296f2b80e3",
    "18174bcf945786e4fd5669dd3dc154ca7e2426c3f6b0b35b71ee5a721dba4990",
    "dc35ebc8a00c499dcf0dd53efb295d1248ef4d81ccae68cc9db22b7c1e4ebf18",
}
SKIP = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".workspace",
    "dist",
    "output",
}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".json",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".sql",
    ".lock",
    ".txt",
}


def publishable_files(root: Path):
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in SKIP for part in relative.parts):
            continue
        yield path


def inspect(root: Path = ROOT) -> list[str]:
    errors = []
    for path in publishable_files(root):
        relative = path.relative_to(root)
        if path.is_symlink():
            errors.append(f"{relative}: symlinks are not release inputs")
            continue
        if (
            path.name.startswith(".env")
            or path.name in {"demo-credentials.json", "config.json", ".DS_Store"}
            or path.name.endswith(".server.lock")
            or ".sqlite" in path.name
            or path.suffix in {".db", ".pyc", ".pem", ".key"}
        ):
            errors.append(f"{relative}: private or generated workspace artifact")
            continue
        if path.suffix == ".png" and relative.parts[:2] == ("docs", "images"):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {
            "LICENSE",
            ".gitignore",
            ".python-version",
        }:
            errors.append(f"{relative}: unexpected release file type")
            continue
        text = path.read_text()
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", str(relative) + " " + text)
        if any(
            hashlib.sha256(token.lower().encode()).hexdigest() in LEGACY_HASHES for token in tokens
        ):
            errors.append(f"{relative}: legacy identifier")
        if re.search("/" + r"(?:Users|home)/[a-zA-Z0-9_.-]+/", text):
            errors.append(f"{relative}: private absolute path")
        if re.search(r"sk-" + r"[a-zA-Z0-9_-]{20,}", text) or re.search(
            r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text
        ):
            errors.append(f"{relative}: possible credential material")
    return errors


if __name__ == "__main__":
    failures = inspect()
    if failures:
        raise SystemExit("\n".join(failures))
    print("Release content checks passed. Review the file list before publication.")
