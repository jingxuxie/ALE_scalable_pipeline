from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "examples" / "review"
EXPECTED_RELEASE_IDENTITIES = {
    "generic-affine": {
        "source_project_id": "generic-affine-demo",
        "task_id": "generic-hard-affine-recovery",
        "source_build_id": "build_152d13a0aee52641a6aded28564bfd508ef3536940d84fd57469becf3b0262fc",
        "source_task_build_id": "task-build_93e633ede1300b8058ed1df6835c2569d18a40b8d5ad29a08a52f9810947e5f6",
    },
    "hnn-canonical-recovery": {
        "source_project_id": "hnn-hard-grounded-suite",
        "task_id": "hnn-hard-canonical-recovery",
        "source_build_id": "build_0cf376e7c0768c651ea764eb481f1940698bebc71b90a3442bfd546020cdc624",
        "source_task_build_id": "task-build_3a10cff7e4b9c5403f483e12c1612fcfebc52539703d58aae96bda073867bc17",
    },
    "hnn-coupled-identification": {
        "source_project_id": "hnn-hard-grounded-suite",
        "task_id": "hnn-hard-coupled-identification",
        "source_build_id": "build_0cf376e7c0768c651ea764eb481f1940698bebc71b90a3442bfd546020cdc624",
        "source_task_build_id": "task-build_7a91d9183f43862779d49d70bf74053a031711aabdcc5ea5769dbd5c77917570",
    },
    "hnn-variable-nbody": {
        "source_project_id": "hnn-hard-grounded-suite",
        "task_id": "hnn-hard-variable-nbody",
        "source_build_id": "build_0cf376e7c0768c651ea764eb481f1940698bebc71b90a3442bfd546020cdc624",
        "source_task_build_id": "task-build_f4c2b72b823dc6bbc6df27b996449cdc785fcd2651223835e958b1a104c2de48",
    },
}
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.task_families.generic import (  # noqa: E402
    build_task_files as build_generic_task_files,
)
from paper2ale.task_families.hnn_hard import (  # noqa: E402
    build_task_files as build_hnn_hard_task_files,
)


class ReviewExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hnn_project = json.loads(
            (ROOT / "examples" / "hnn_hard" / "project.json").read_text(
                encoding="utf-8"
            )
        )
        seed = int(cls.hnn_project["defaults"]["master_seed"])
        cls.hnn_builds = {
            task["id"]: {
                item.path: item
                for item in build_hnn_hard_task_files(
                    cls.hnn_project, task, master_seed=seed
                )
            }
            for task in cls.hnn_project["tasks"]
        }
        generic_project = json.loads(
            (ROOT / "examples" / "generic" / "project.json").read_text(
                encoding="utf-8"
            )
        )
        generic_seed = int(generic_project["defaults"]["master_seed"])
        cls.current_builds = dict(cls.hnn_builds)
        cls.current_builds.update(
            {
                task["id"]: {
                    item.path: item
                    for item in build_generic_task_files(
                        generic_project, task, master_seed=generic_seed
                    )
                }
                for task in generic_project["tasks"]
            }
        )

    def test_manifests_bind_every_concrete_artifact(self) -> None:
        manifests = sorted(REVIEW_ROOT.glob("*/review_manifest.json"))
        self.assertEqual(
            {path.parent.name for path in manifests},
            {
                "generic-affine",
                "hnn-canonical-recovery",
                "hnn-coupled-identification",
                "hnn-variable-nbody",
            },
        )
        for manifest_path in manifests:
            example_root = manifest_path.parent
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["schema_version"], "paper2ale.review-example/v1"
            )
            self.assertEqual(manifest["instance_id"], "000")
            for key, value in EXPECTED_RELEASE_IDENTITIES[
                example_root.name
            ].items():
                self.assertEqual(manifest[key], value)
            self.assertIs(manifest["public_review_fixture"], True)
            self.assertIs(manifest["usable_for_live_evaluation"], False)
            declared = {entry["path"] for entry in manifest["files"]}
            self.assertEqual(len(declared), len(manifest["files"]))
            actual = {
                path.relative_to(example_root).as_posix()
                for path in example_root.rglob("*")
                if path.is_file()
                and path.name not in {"README.md", "review_manifest.json"}
            }
            self.assertEqual(declared, actual)
            for entry in manifest["files"]:
                self.assertNotIn("..", Path(entry["path"]).parts)
                self.assertNotIn("..", Path(entry["source_path"]).parts)
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

            task_files = self.current_builds.get(manifest["task_id"])
            if task_files is not None:
                for entry in manifest["files"]:
                    source = task_files.get(entry["source_path"])
                    self.assertIsNotNone(source, entry["source_path"])
                    self.assertEqual(
                        (example_root / entry["path"]).read_bytes(), source.data
                    )
                    if entry["visibility"] == "participant":
                        self.assertEqual(source.visibility, "agent")

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
            "hnn-coupled-identification: correct=PASS incorrect=REJECTED",
            completed.stdout,
        )
        self.assertIn(
            "hnn-variable-nbody: correct=PASS incorrect=REJECTED",
            completed.stdout,
        )
        self.assertIn(
            "hnn-canonical-recovery: correct=PASS incorrect=REJECTED",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
