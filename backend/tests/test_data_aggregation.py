import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.scripts.data_aggregation import (
    convert_client_table_to_dashboard_schema,
    save_dashboard_clients_to_json,
)


class DashboardAggregationTests(unittest.TestCase):
    def test_output_keeps_frontend_keys_and_exposes_audit_details(self):
        table = pd.DataFrame([{
            "entity_id": "E01",
            "entity_name": "Example Ltd",
            "sector": "services",
            "txn_banking_total_zar": 20.0,
            "cross_border_total_zar": 10.0,
            "trade_finance_total_zar": 5.0,
            "lending_signal_total_zar": 5.0,
            "lending_signal_txn_count": 6,
            "syn_bank_observed_total_zar": 40.0,
            "transactional_banking": 100.0,
            "global_markets": 50.0,
            "investment_banking": 50.0,
            "total": 200.0,
            "transactional_banking_confidence": "low",
            "global_markets_confidence": "medium",
            "investment_banking_confidence": "high",
            "transactional_banking_score": 0.25,
            "global_markets_score": 0.5,
            "investment_banking_score": 0.75,
            "total_score": 0.6,
        }])
        details = {
            "formulas": {
                "Example Ltd": {
                    "products": {},
                    "pillars": {
                        "transactional_banking": {
                            "confidence_reasons": [{
                                "product": "payments",
                                "status": "proxy",
                                "missing_fields": ["cost_of_sales"],
                            }]
                        }
                    },
                }
            },
            "missing_rows": [{"company": "Example Ltd", "cost_of_sales": None}],
        }

        record = convert_client_table_to_dashboard_schema(
            table,
            calculation_details=details,
            missing_data={"Example Ltd": ["cost_of_sales"]},
        )[0]

        self.assertEqual(record["txn_banking_pct"], 50.0)
        self.assertEqual(record["cross_border_pct"], 25.0)
        self.assertEqual(record["trade_finance_pct"], 12.5)
        self.assertEqual(record["opportunity_score"], 60.0)
        self.assertEqual(record["confidence"]["transactional_banking"]["level"], "low")
        self.assertEqual(
            record["confidence"]["transactional_banking"]["reasons"][0]["product"],
            "payments",
        )
        self.assertEqual(record["missing_data"]["fields"], ["cost_of_sales"])
        self.assertIn("formula", record["score_calculation"])

    def test_json_writer_emits_strict_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client_data.json"
            save_dashboard_clients_to_json([{"entity_id": "E01"}], path)
            self.assertEqual(json.loads(path.read_text()), [{"entity_id": "E01"}])


if __name__ == "__main__":
    unittest.main()
