from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "examples" / "review"


class ReviewExampleTests(unittest.TestCase):
    def test_manifests_bind_every_concrete_artifact(self) -> None:
        for example in ("generic-affine", "hnn-canonical-recovery"):
            example_root = REVIEW_ROOT / example
            manifest = json.loads(
                (example_root / "review_manifest.json").read_text(encoding="utf-8")
            )
            declared = {entry["path"] for entry in manifest["files"]}
            actual = {
                path.relative_to(example_root).as_posix()
                for path in example_root.rglob("*")
                if path.is_file()
                and path.name not in {"README.md", "review_manifest.json"}
            }
            self.assertEqual(declared, actual)
            for entry in manifest["files"]:
                path = example_root / entry["path"]
                self.assertEqual(path.stat().st_size, entry["size_bytes"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"]
                )
                expected_visibility = (
                    "participant"
                    if entry["path"].startswith("participant/")
                    else "reviewer_only"
                )
                self.assertEqual(entry["visibility"], expected_visibility)

    def test_correct_answers_pass_and_incorrect_answers_fail(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REVIEW_ROOT / "run_checks.py")],
            cwd=ROOT,
            capture_output=True,
            check=False,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "generic-affine: correct=PASS incorrect=REJECTED", completed.stdout
        )
        self.assertIn(
            "hnn-canonical-recovery: correct=PASS incorrect=REJECTED",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
