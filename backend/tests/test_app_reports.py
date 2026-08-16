import unittest
from unittest.mock import Mock, patch

from backend import app as app_module


class AutomaticReportTests(unittest.TestCase):
    def test_generates_only_missing_reports_for_top_three_companies(self):
        clients = [
            {"entity_id": "E01", "opportunity_score": 10},
            {"entity_id": "E02", "opportunity_score": 30},
            {"entity_id": "E03", "opportunity_score": 20},
            {"entity_id": "E04", "opportunity_score": 5},
            {"entity_id": "E05", "opportunity_score": "not available"},
        ]
        reports = Mock()
        reports.status.side_effect = lambda client: {
            "available": client["entity_id"] == "E02"
        }

        with (
            patch.object(app_module, "REPORTS", reports),
            patch.object(
                app_module,
                "_clients_with_current_timing",
                return_value=clients,
            ),
            patch.object(app_module, "_generate_report") as generate,
        ):
            generated = app_module._generate_missing_top_company_reports()

        self.assertEqual(generated, ["E03", "E01"])
        self.assertEqual(
            [call.args[0]["entity_id"] for call in generate.call_args_list],
            ["E03", "E01"],
        )
        self.assertEqual(
            [call.args[0]["entity_id"] for call in reports.status.call_args_list],
            ["E02", "E03", "E01"],
        )


if __name__ == "__main__":
    unittest.main()
