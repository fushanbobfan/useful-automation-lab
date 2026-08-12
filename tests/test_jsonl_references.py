import json
import unittest

import useful_automation_lab
from useful_automation_lab.jsonl_references import audit_jsonl_references


class JsonlReferenceTests(unittest.TestCase):
    def setUp(self):
        self.parents = [
            {"id": "p1", "secret": "parent-one"},
            {"id": "p2", "secret": "parent-two"},
            {"id": "p3", "secret": "parent-three"},
        ]
        self.children = [
            {"id": "c1", "parent_id": "p1", "payload": "child-one"},
            {"id": "c2", "parent_id": "p1", "payload": "child-two"},
            {"id": "c3", "parent_id": "p2", "payload": "child-three"},
            {"id": "c4", "parent_id": "missing", "payload": "child-four"},
            {"id": "c5", "parent_id": "missing", "payload": "child-five"},
        ]

    def test_public_api_and_reference_summary(self):
        self.assertIs(
            useful_automation_lab.audit_jsonl_references,
            audit_jsonl_references,
        )
        report = audit_jsonl_references(
            self.parents, self.children, max_orphan_references=2
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "parent_record_count": 3,
                "child_record_count": 5,
                "referenced_parent_count": 2,
                "unreferenced_parent_count": 1,
                "orphan_reference_count": 2,
                "distinct_orphan_id_count": 1,
                "maximum_children_per_parent": 2,
                "parents_over_max_children": 0,
            },
        )
        self.assertEqual(
            report["orphan_references"],
            [{"id": "missing", "child_count": 2}],
        )
        self.assertEqual(report["unreferenced_parents"], [{"id": "p3"}])

    def test_all_integrity_gates_report_failures(self):
        report = audit_jsonl_references(
            self.parents,
            self.children,
            max_orphan_references=1,
            max_unreferenced_parents=0,
            max_children_per_parent=1,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [failure["metric"] for failure in report["failures"]],
            [
                "orphan_reference_count",
                "unreferenced_parent_count",
                "maximum_children_per_parent",
            ],
        )
        self.assertEqual(report["fanout_violations"], [{"id": "p1", "child_count": 2}])

    def test_report_only_copies_join_identifiers(self):
        report = audit_jsonl_references(
            self.parents, self.children, max_orphan_references=2
        )
        rendered = json.dumps(report)

        self.assertNotIn("parent-one", rendered)
        self.assertNotIn("child-one", rendered)
        self.assertFalse(report["settings"]["scalar_values_reported_beyond_ids"])

    def test_details_are_deterministic_and_bounded(self):
        report = audit_jsonl_references(
            self.parents,
            self.children,
            max_orphan_references=2,
            max_children_per_parent=0,
            max_details=1,
        )

        self.assertEqual(
            report["largest_parent_cardinalities"],
            [{"id": "p1", "child_count": 2}],
        )
        self.assertEqual(
            report["details_truncated"],
            {
                "orphan_references": False,
                "unreferenced_parents": False,
                "parent_cardinalities": True,
                "fanout_violations": True,
            },
        )

    def test_numeric_identifiers_preserve_type(self):
        report = audit_jsonl_references(
            [{"key": 1}, {"key": "1"}],
            [{"owner": 1}, {"owner": "1"}],
            parent_id_field="key",
            child_reference_field="owner",
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["referenced_parent_count"], 2)

    def test_invalid_records_fields_ids_and_thresholds_are_rejected(self):
        invalid_calls = [
            ([], self.children, {}),
            (self.parents, [], {}),
            (self.parents, self.children, {"parent_id_field": ""}),
            (self.parents, self.children, {"max_orphan_references": -1}),
            (self.parents, self.children, {"max_children_per_parent": True}),
            (self.parents, self.children, {"max_details": -1}),
        ]
        for parents, children, settings in invalid_calls:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                audit_jsonl_references(parents, children, **settings)

        with self.assertRaisesRegex(ValueError, "duplicate ID"):
            audit_jsonl_references(
                [{"id": "same"}, {"id": "same"}], self.children
            )
        with self.assertRaisesRegex(ValueError, "string or number"):
            audit_jsonl_references([{"id": ["nested"]}], self.children)
        with self.assertRaisesRegex(ValueError, "missing parent_id"):
            audit_jsonl_references(self.parents, [{"id": "child"}])


if __name__ == "__main__":
    unittest.main()
