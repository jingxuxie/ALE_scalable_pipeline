from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from paper2ale.bindings import make_workflow_binding, parse_workflow_binding
from paper2ale.triage import mine_task_candidates
from tests.test_workflow import valid_workflow


class WorkflowBindingTests(unittest.TestCase):
    def test_binding_is_content_derived_closed_and_tamper_evident(self) -> None:
        workflow = valid_workflow()
        candidate = mine_task_candidates([workflow])[0]
        binding = make_workflow_binding("generic", workflow, candidate)
        parsed_workflow, parsed_candidate = parse_workflow_binding(
            binding, expected_family="generic"
        )
        self.assertEqual(parsed_workflow, workflow)
        self.assertEqual(parsed_candidate, candidate)
        self.assertRegex(binding["binding_id"], r"^binding_[0-9a-f]{64}$")

        tampered = copy.deepcopy(binding)
        tampered["workflow"]["title"] = "Unbound replacement"
        with self.assertRaisesRegex(
            ValueError, "canonical candidate|does not match its content"
        ):
            parse_workflow_binding(tampered, expected_family="generic")

        invented = replace(candidate, evidence_ids=())
        with self.assertRaisesRegex(ValueError, "canonical candidate"):
            make_workflow_binding("generic", workflow, invented)


if __name__ == "__main__":
    unittest.main()
