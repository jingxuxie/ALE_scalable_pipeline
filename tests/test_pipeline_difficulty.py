from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.pipeline import _build_task_in_memory, audit_project  # noqa: E402
from paper2ale.task_families.hnn_hard import build_task_files  # noqa: E402


class PipelineDifficultyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = json.loads(
            (ROOT / "examples" / "hnn_hard" / "project.json").read_text(
                encoding="utf-8"
            )
        )
        cls.task = cls.project["tasks"][0]
        cls.seed = cls.project["defaults"]["master_seed"]

    def test_builder_consumption_manifest_is_a_preflight_gate(self) -> None:
        _, _, qa = _build_task_in_memory(
            self.project,
            self.task,
            self.seed,
            None,
        )
        self.assertEqual(qa["checks"]["difficulty"]["status"], "passed")

        original = build_task_files(
            self.project,
            self.task,
            master_seed=self.seed,
        )
        tampered = [
            BuildFile(item.path, item.data.replace(b'"level": "hard"', b'"level": "medium"'), item.visibility, item.executable)
            if item.path == "author/difficulty_manifest.json"
            else item
            for item in original
        ]

        def tampered_builder(*args, **kwargs):
            return tampered

        with patch("paper2ale.pipeline._builder_for", return_value=tampered_builder):
            with self.assertRaisesRegex(ValueError, "difficulty manifest"):
                _build_task_in_memory(self.project, self.task, self.seed, None)

    def test_cli_level_override_reaches_builder_and_qa(self) -> None:
        project = dict(self.project)
        project["tasks"] = [self.task]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "project.json"
            path.write_text(json.dumps(project), encoding="utf-8")
            report = audit_project(path, difficulty_level="medium")
        self.assertTrue(report["publication_ready"])
        check = report["tasks"][0]["qa"]["checks"]["difficulty"]
        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["level"], "medium")


if __name__ == "__main__":
    unittest.main()
