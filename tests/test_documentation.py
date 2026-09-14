import os
import re
import subprocess
import sys
from pathlib import Path

from tools.check_docs import check_links
from tools.check_release import inspect

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_links_and_release_content():
    assert not check_links()
    assert not inspect()


def test_documented_offline_quickstart(tmp_path):
    doc = (ROOT / "docs/development.md").read_text()
    block = doc.split("<!-- offline-quickstart:start -->")[1].split(
        "<!-- offline-quickstart:end -->"
    )[0]
    script = re.search(r"```bash\n(.*?)```", block, re.S).group(1)
    env = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run(
        ["sh", "-eu", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "backup.sqlite3").exists()


def test_release_guard_detects_accidental_artifacts(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "notes.md").write_text("/" + "Users/" + "private-person/project/file")
    (tmp_path / "credentials.txt").write_text("sk-" + "A" * 30)
    result = inspect(tmp_path)
    assert any("artifact" in item for item in result)
    assert any("private absolute path" in item for item in result)
    assert any("credential material" in item for item in result)


def test_release_images_have_matching_extensions_and_limited_locations(tmp_path):
    image = (ROOT / "docs/images/review.jpg").read_bytes()
    images = tmp_path / "docs/images"
    images.mkdir(parents=True)
    (images / "review.jpg").write_bytes(image)
    assert inspect(tmp_path) == []
    (images / "misnamed.png").write_bytes(image)
    assert any("does not match" in error for error in inspect(tmp_path))
    (tmp_path / "unrelated.jpg").write_bytes(image)
    (images / "unexpected.bin").write_bytes(b"unrelated data")
    errors = inspect(tmp_path)
    assert any("unrelated.jpg: unexpected" in error for error in errors)
    assert any("unexpected.bin: unexpected" in error for error in errors)
