from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "output"}
EXCLUDED_FILES = {".env", ".streamlit/secrets.toml"}


def skip(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    parts = set(rel.split("/"))
    if parts & EXCLUDED_DIRS:
        return True
    if rel in EXCLUDED_FILES:
        return True
    if path.suffix in {".pyc", ".pyo"}:
        return True
    return False


def main() -> int:
    out = DIST / "galaxy-voc-router-edition.zip"
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if path.is_dir() or skip(path):
                continue
            zf.write(path, arcname=path.relative_to(ROOT))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
