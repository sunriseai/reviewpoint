"""Check every local Markdown link, including images, without following external URLs."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_links(root: Path = ROOT) -> list[str]:
    errors = []
    files = [root / "README.md", root / "CONTRIBUTING.md", root / "frontend/README.md"]
    files.extend((root / "docs").rglob("*.md"))
    files.extend((root / "examples").rglob("*.md"))
    for path in files:
        text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                continue
            destination = (path.parent / target.split("#", 1)[0]).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                errors.append(f"{path.relative_to(root)}: broken or external local link {target}")
    return errors


if __name__ == "__main__":
    failures = check_links()
    if failures:
        raise SystemExit("\n".join(failures))
    print("All documentation links are local and valid.")
