"""Do not apply historical patches to incompatible current portal sources."""
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts import reproduce_baseline


class HistoricalReconstructionTests(unittest.TestCase):
    def test_matching_source_hash_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "support_agent/example.py"
            path.parent.mkdir(); path.write_text("historical fixture")
            self.assertEqual([], reproduce_baseline.check_source(root, {"support_agent/example.py": hashlib.sha256(path.read_bytes()).hexdigest()}))

    def test_changed_and_missing_source_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "changed.py").write_text("new source")
            result = reproduce_baseline.check_source(root, {"changed.py": "old hash", "missing.py": "old hash"})
            self.assertEqual(["changed.py", "missing.py"], result)

    def test_source_is_required_and_current_code_is_rejected_before_patching(self):
        for argv in ([], ["--source-root", str(reproduce_baseline.ROOT)]):
            with self.subTest(argv=argv), patch.object(reproduce_baseline.subprocess, "run") as command:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                    reproduce_baseline.main(argv)
                self.assertEqual(2, result.exception.code)
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
