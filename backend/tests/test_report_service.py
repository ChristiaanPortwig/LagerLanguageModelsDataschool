import json
import tempfile
import unittest

from backend.scripts.report_service import ReportService


class ReportServiceTests(unittest.TestCase):
    @staticmethod
    def client():
        return {
            "entity_id": "E01",
            "entity_name": "Example Ltd",
            "sector": "services",
            "opportunity_score": 72.5,
            "estimated_total_wallet_zar": 1_000_000,
            "wallet_gap_zar": 400_000,
            "relationship_manager": {
                "employee_id": "RM-MOCK-001",
                "name": "Example Manager",
                "title": "Relationship Manager",
                "email": "manager@example.invalid",
                "is_mock": True,
            },
            "timing_intelligence": {
                "payment_timing": {"predicted_payment_date": "2026-09-20"},
                "engagement_prediction": {
                    "recommended_engagement_date": "2026-09-01",
                    "engage_now": False,
                    "recommended_action": "Confirm payment requirements.",
                },
            },
            "score_calculation": {
                "formula": "weighted pillar score",
                "weights": {
                    "gap_weight": 0.5,
                    "sens_weight": 0.4,
                    "relationship_weight": 0.1,
                },
            },
            "wallet_calculation": {
                "pillars": {
                    "transactional_banking": {
                        "formula": "payments + liquidity",
                        "value": 500_000,
                    }
                },
                "products": {
                    "payments": {
                        "tier": "A",
                        "formula": "revenue * payment rate",
                        "inputs": {"revenue": 10_000_000},
                        "value": 250_000,
                    }
                },
            },
        }

    def test_generates_downloadable_two_page_report_with_manager_and_formulas(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ReportService(directory)
            client = self.client()

            status = service.generate(
                client,
                "Relationship snapshot.\n\nOpportunity.\n\nRecommended action.",
            )
            path = service.download_path(client)
            report_html = path.read_text(encoding="utf-8")

        self.assertTrue(status["available"])
        self.assertEqual(report_html.count('<section class="page">'), 2)
        self.assertIn("Example Manager", report_html)
        self.assertIn("Formulas used", report_html)
        self.assertIn("revenue * payment rate", report_html)

    def test_changed_client_data_deletes_stale_report(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ReportService(directory)
            client = self.client()
            service.generate(client, "Current report.")
            report_path = service.download_path(client)
            changed = {**client, "opportunity_score": 88.0}

            status = service.status(changed)

            self.assertFalse(status["available"])
            self.assertFalse(report_path.exists())
            self.assertEqual(
                json.loads(service.manifest_path.read_text(encoding="utf-8")),
                {},
            )

    def test_loads_mock_relationship_assignment_from_json_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ReportService(directory)
            service.relationship_path.write_text(
                json.dumps({
                    "directory_name": "Mock directory",
                    "is_mock": True,
                    "assignments": {
                        "E01": {
                            "employee_id": "RM-1",
                            "name": "Assigned Person",
                            "title": "Relationship Manager",
                            "email": "assigned@example.invalid",
                        }
                    },
                }),
                encoding="utf-8",
            )

            manager = service.relationship_manager("E01")

        self.assertEqual(manager["name"], "Assigned Person")
        self.assertTrue(manager["is_mock"])


if __name__ == "__main__":
    unittest.main()
