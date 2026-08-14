from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.orchestration import orchestration_manifest_json_schema  # noqa: E402
from paper2ale.task_families.generic import protocol_json_schema  # noqa: E402
from paper2ale.workflow import workflow_json_schema  # noqa: E402


class ShippedSchemaTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))

    def without_id(self, value: dict) -> dict:
        copied = copy.deepcopy(value)
        copied.pop("$id", None)
        return copied

    def test_generated_intermediate_contracts_match_shipped_schemas(self) -> None:
        pairs = (
            ("workflow.schema.json", workflow_json_schema()),
            ("generic_protocol.schema.json", protocol_json_schema()),
            (
                "orchestration_manifest.schema.json",
                orchestration_manifest_json_schema(),
            ),
        )
        for name, generated in pairs:
            with self.subTest(name=name):
                shipped = self.load(name)
                self.assertEqual(self.without_id(shipped), self.without_id(generated))
                self.assertEqual(
                    shipped["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )

    def test_asset_snapshot_schema_is_the_project_contract_standalone(self) -> None:
        project = self.load("project.schema.json")
        shipped = self.load("asset_snapshot.schema.json")
        expected = copy.deepcopy(project["$defs"]["asset_snapshot"])
        self.assertEqual(
            {key: value for key, value in shipped.items() if not key.startswith("$")},
            expected,
        )
        self.assertEqual(shipped["$defs"]["asset_file"], project["$defs"]["asset_file"])

    def test_source_and_installed_package_schema_copies_match(self) -> None:
        packaged = ROOT / "src" / "paper2ale" / "schemas"
        source_names = sorted(path.name for path in (ROOT / "schemas").glob("*.json"))
        packaged_names = sorted(path.name for path in packaged.glob("*.json"))
        self.assertEqual(packaged_names, source_names)
        for name in source_names:
            with self.subTest(name=name):
                self.assertEqual(
                    (packaged / name).read_text(encoding="utf-8").rstrip("\n"),
                    (ROOT / "schemas" / name)
                    .read_text(encoding="utf-8")
                    .rstrip("\n"),
                )


if __name__ == "__main__":
    unittest.main()
