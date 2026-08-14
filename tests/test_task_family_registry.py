from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper2ale.packaging import BuildFile  # noqa: E402
from paper2ale.task_families import (  # noqa: E402
    TASK_FAMILIES,
    register_task_family,
    registered_task_families,
    task_family,
)


class TaskFamilyRegistryTests(unittest.TestCase):
    def test_builtin_hnn_is_registered(self) -> None:
        self.assertIs(TASK_FAMILIES["hnn"], task_family("hnn").builder)
        self.assertIn("hnn", registered_task_families())

    def test_explicit_registration_records_capabilities(self) -> None:
        def builder(*args, **kwargs):
            return [BuildFile("main.py", b"pass\n", "agent")]

        name = "unit-test-family"
        register_task_family(
            name,
            builder,
            supported_difficulty_levels=("easy", "hard"),
            replace=True,
        )
        self.assertIs(task_family(name).builder, builder)
        self.assertEqual(
            task_family(name).supported_difficulty_levels,
            ("easy", "hard"),
        )

    def test_unknown_family_error_lists_available_plugins(self) -> None:
        with self.assertRaisesRegex(ValueError, "registered families"):
            task_family("does-not-exist")


if __name__ == "__main__":
    unittest.main()
