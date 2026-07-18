import unittest

from useful_automation_lab.jsonl_audit import audit_jsonl


class JsonlAuditTests(unittest.TestCase):
    def test_valid_records_and_allowed_blank_lines_pass(self):
        report = audit_jsonl(
            [
                '{"id":1,"event":"started"}\n',
                "\n",
                '{"id":2,"event":"finished"}\n',
            ],
            required_fields=["id", "event"],
            unique_field="id",
            allow_blank_lines=True,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "total_lines": 3,
                "blank_lines": 1,
                "object_records": 2,
                "valid_records": 2,
                "invalid_lines": 0,
                "duplicate_records": 0,
                "error_count": 0,
                "reported_errors": 0,
                "truncated_errors": 0,
            },
        )

    def test_reports_data_quality_errors_in_line_order(self):
        report = audit_jsonl(
            [
                '{"id":1,"event":"started"}\n',
                "\n",
                "[]\n",
                '{"id":2,"id":3,"event":"duplicate key"}\n',
                '{"id":2}\n',
                '{"id":1,"event":"repeated"}\n',
                '{"id":NaN,"event":"invalid constant"}\n',
                "{\n",
            ],
            required_fields=["id", "event"],
            unique_field="id",
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [error["code"] for error in report["errors"]],
            [
                "blank_line",
                "non_object_record",
                "duplicate_json_key",
                "missing_required_fields",
                "duplicate_unique_value",
                "invalid_json_constant",
                "invalid_json",
            ],
        )
        self.assertEqual(report["summary"]["invalid_lines"], 7)
        self.assertEqual(report["summary"]["duplicate_records"], 1)
        self.assertEqual(report["errors"][4]["first_line"], 1)

    def test_line_size_is_measured_in_utf8_bytes(self):
        report = audit_jsonl(
            ['{"value":"é"}\n'],
            max_line_bytes=13,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["errors"][0]["code"], "line_too_large")
        self.assertEqual(report["errors"][0]["actual_bytes"], 14)
        self.assertEqual(report["summary"]["object_records"], 1)

    def test_error_collection_is_bounded_without_hiding_totals(self):
        report = audit_jsonl(["\n", "\n", "\n"], max_errors=2)

        self.assertEqual(report["summary"]["error_count"], 3)
        self.assertEqual(report["summary"]["reported_errors"], 2)
        self.assertEqual(report["summary"]["truncated_errors"], 1)
        self.assertEqual(len(report["errors"]), 2)

    def test_invalid_configuration_and_line_values_are_rejected(self):
        for fields in ("id", [""], ["id", "id"], [1]):
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(ValueError, "required_fields"):
                    audit_jsonl([], required_fields=fields)
        for name, value in (
            ("max_line_bytes", 0),
            ("max_errors", True),
            ("unique_field", ""),
            ("allow_blank_lines", 1),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaisesRegex(ValueError, name):
                    audit_jsonl([], **{name: value})
        with self.assertRaisesRegex(ValueError, "line 1"):
            audit_jsonl([b"{}"])


if __name__ == "__main__":
    unittest.main()
