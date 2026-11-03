#!/usr/bin/env python3
"""Package source and synthetic fixtures only; no private exports or runtime DB."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {"README.md", "README.zh-CN.md", "pyproject.toml",
             "Dockerfile", "compose.yaml", ".env.example", ".gitignore", ".dockerignore", "start-demo.command",
             "knowledge/README.md", "knowledge/README.zh-CN.md"}
SOURCE_DIRS = {"support_agent", "scripts", "tests", "docs", "evals"}
EXCLUDED = {"__pycache__", ".DS_Store", "__MACOSX", ".pytest_cache", ".mypy_cache", ".ruff_cache",
            ".cache", ".git", ".venv", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".swp", ".swo", ".bak"}


def release_files(root: Path = ROOT):
    """Keep runnable sources and audit fixtures, excluding generated state."""
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink() or EXCLUDED.intersection(relative.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES or path.name.startswith(("._", ".coverage")) or path.name.endswith(("~", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm")):
            continue
        if str(relative) != ".env.example" and (path.name.startswith(".env") or path.suffix == ".env"):
            continue
        if str(relative) in TOP_FILES or relative.parts[0] in SOURCE_DIRS:
            files.append(path)
    return files


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    target = ROOT / f"dist/ai_customer_service_agent-lumen-v{version}.zip"
    target.parent.mkdir(exist_ok=True)
    files = release_files()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("ai_customer_service_agent") / path.relative_to(ROOT))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n")
    print(json.dumps({"archive": str(target), "files": len(files), "bytes": target.stat().st_size, "sha256": digest}, indent=2))


if __name__ == "__main__":
    main()
