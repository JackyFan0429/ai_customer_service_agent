"""Release archives keep evidence and exclude caches or runtime state."""
import tempfile
import unittest
from pathlib import Path

from scripts.package_demo import release_files


class ReleasePackagingTests(unittest.TestCase):
    def create(self, root, names):
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")

    def test_sources_and_frozen_evidence_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {"README.md", ".env.example", "support_agent/main.py", "tests/fixtures/input.json",
                        "evals/baselines/pre_iteration.patch", "docs/legacy/README.md", "docs/assets/badge.svg"}
            self.create(root, expected | {"private-export.json", "runtime/state.json", "dist/previous.zip"})
            self.assertEqual(expected, {str(p.relative_to(root)) for p in release_files(root)})

    def test_nested_caches_credentials_and_databases_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            excluded = {"docs/.DS_Store", "docs/._image.png", "docs/__MACOSX/x", "tests/.pytest_cache/x",
                        "support_agent/__pycache__/module.pyc", "scripts/.ruff_cache/x", "docs/.cache/x",
                        "docs/node_modules/x.js", "support_agent/.env", "docs/.env.example", "tests/test.db",
                        "tests/test.db-wal", "tests/test.sqlite-shm", "docs/notes.md~", "docs/notes.bak",
                        "tests/.coverage", "tests/.coverage.worker", "scripts/.venv/python"}
            self.create(root, excluded | {"docs/keep.md"})
            self.assertEqual([root / "docs/keep.md"], release_files(root))

    def test_symlinks_are_not_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create(root, ["private.txt", "docs/keep.md"])
            (root / "docs/link.txt").symlink_to(root / "private.txt")
            self.assertEqual([root / "docs/keep.md"], release_files(root))

    def test_archive_input_order_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create(root, ["docs/z.md", "support_agent/z.py", "README.md", "docs/a.md"])
            names = [str(p.relative_to(root)) for p in release_files(root)]
            self.assertEqual(sorted(names), names)


if __name__ == "__main__":
    unittest.main()
