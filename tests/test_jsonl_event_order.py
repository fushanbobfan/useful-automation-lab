import unittest

from useful_automation_lab.jsonl_event_order import audit_jsonl_event_order


class JsonlEventOrderTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"event_id": "e1", "stream": "a", "timestamp": "2026-01-01T00:00:00Z", "sequence": 1},
            {"event_id": "e2", "stream": "b", "timestamp": "2026-01-01T00:00:30Z", "sequence": 10},
            {"event_id": "e3", "stream": "a", "timestamp": "2026-01-01T00:02:00Z", "sequence": 3},
            {"event_id": "e4", "stream": "a", "timestamp": "2026-01-01T00:01:00Z", "sequence": 3},
            {"event_id": "e5", "stream": "b", "timestamp": "2026-01-01T00:00:20Z", "sequence": 9},
            {"event_id": "e2", "stream": "b", "timestamp": "2026-01-01T00:00:40Z", "sequence": 10},
        ]

    def test_report_counts_grouped_order_violations(self):
        report = audit_jsonl_event_order(
            self.records,
            group_field="stream",
            sequence_field="sequence",
            max_duplicate_event_ids=1,
            max_timestamp_regressions=2,
            max_sequence_violations=3,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "record_count": 6,
                "group_count": 2,
                "duplicate_event_ids": 1,
                "timestamp_regressions": 2,
                "sequence_regressions": 1,
                "duplicate_sequences": 1,
                "sequence_gap_transitions": 1,
                "missing_sequence_values": 1,
                "sequence_violations": 3,
                "violation_count": 6,
                "reported_details": 6,
                "truncated_details": 0,
            },
        )
        self.assertEqual(
            [detail["code"] for detail in report["details"]],
            [
                "sequence_gap",
                "timestamp_regression",
                "duplicate_sequence",
                "timestamp_regression",
                "sequence_regression",
                "duplicate_event_id",
            ],
        )
        self.assertFalse(report["settings"]["record_values_reported"])

    def test_threshold_failures_are_stably_ordered_and_details_bounded(self):
        report = audit_jsonl_event_order(
            self.records,
            group_field="stream",
            sequence_field="sequence",
            max_details=2,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [failure["metric"] for failure in report["failures"]],
            ["duplicate_event_ids", "timestamp_regressions", "sequence_violations"],
        )
        self.assertEqual(len(report["details"]), 2)
        self.assertEqual(report["summary"]["truncated_details"], 4)

    def test_global_timestamps_compare_normalized_instants(self):
        report = audit_jsonl_event_order(
            [
                {"event_id": 1, "timestamp": "2026-01-01T00:00:00Z"},
                {"event_id": 2, "timestamp": "2026-01-01T01:00:00+01:00"},
                {"event_id": 3, "timestamp": "2026-01-01T00:01:00+00:00"},
            ]
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["group_count"], 1)
        self.assertEqual(report["summary"]["timestamp_regressions"], 0)
        self.assertEqual(report["settings"]["timestamp_scope"], "global")

    def test_invalid_records_fields_timestamps_and_sequences_are_rejected(self):
        invalid_calls = [
            ([], {}),
            ([{"event_id": "e1", "timestamp": "2026-01-01T00:00:00"}], {}),
            ([{"event_id": "e1", "timestamp": "not-a-time"}], {}),
            ([{"event_id": True, "timestamp": "2026-01-01T00:00:00Z"}], {}),
            ([{"event_id": "e1"}], {}),
            ([{"event_id": "e1", "timestamp": "2026-01-01T00:00:00Z", "sequence": -1}], {"sequence_field": "sequence"}),
        ]
        for records, settings in invalid_calls:
            with self.subTest(records=records, settings=settings), self.assertRaises(ValueError):
                audit_jsonl_event_order(records, **settings)
        with self.assertRaisesRegex(ValueError, "distinct"):
            audit_jsonl_event_order(
                [{"event_id": "e1", "timestamp": "2026-01-01T00:00:00Z"}],
                timestamp_field="event_id",
            )
        for name in (
            "max_duplicate_event_ids",
            "max_timestamp_regressions",
            "max_sequence_violations",
            "max_details",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                audit_jsonl_event_order(
                    [{"event_id": "e1", "timestamp": "2026-01-01T00:00:00Z"}],
                    **{name: -1},
                )


if __name__ == "__main__":
    unittest.main()
