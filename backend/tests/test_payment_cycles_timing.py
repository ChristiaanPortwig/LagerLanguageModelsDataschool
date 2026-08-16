import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.scripts.payment_cycles_timing import (
    calculate_client_timing_intelligence,
    next_occurrence_of_day,
)
from backend.scripts.pipeline_service import PipelineService


class PaymentCycleTimingTests(unittest.TestCase):
    @staticmethod
    def _ledger(rows, source):
        frame = pd.DataFrame(rows)
        frame["source"] = source
        return frame

    def test_calculates_cycles_payment_window_and_rules_engagement(self):
        transactional = self._ledger([
            {
                "entity_id": "E01", "entity_name": "Example Ltd",
                "date": "2026-06-05", "direction": "inbound", "value_zar": 100,
            },
            {
                "entity_id": "E01", "entity_name": "Example Ltd",
                "date": "2026-07-05", "direction": "inbound", "value_zar": 200,
            },
            {
                "entity_id": "E01", "entity_name": "Example Ltd",
                "date": "2026-07-26", "direction": "outbound", "value_zar": 50,
            },
        ], "transactional")
        cross_border = self._ledger([
            {
                "entity_id": "E01", "entity_name": "Example Ltd",
                "date": "2026-06-20", "direction": "outbound", "value_zar": 5_000,
            },
        ], "cross_border")

        result = calculate_client_timing_intelligence(
            [transactional, cross_border],
            reference_date="2026-08-21",
        )[0]

        self.assertEqual(result["cash_cycle"]["cash_in"]["peak_day"], 5)
        self.assertEqual(result["payment_timing"]["peak_day"], 20)
        self.assertEqual(result["payment_timing"]["predicted_payment_date"], "2026-09-20")
        self.assertEqual(result["payment_timing"]["strategy"], "FX / Cross-Border")
        self.assertEqual(result["engagement_prediction"]["recommended_engagement_date"], "2026-08-21")
        self.assertTrue(result["engagement_prediction"]["engage_now"])
        self.assertEqual(result["engagement_prediction"]["generated_by"], "rules_fallback")

    def test_applies_valid_structured_gemini_prediction(self):
        ledger = self._ledger([
            {
                "entity_id": "E01", "entity_name": "Example Ltd",
                "date": "2026-07-25", "direction": "outbound", "value_zar": 100,
            },
        ], "transactional")
        gemini = MagicMock()
        gemini.call_gemini_structured_json.return_value = {
            "predictions": [{
                "entity_id": "E01",
                "recommended_engagement_date": "2026-08-22",
                "engagement_priority": "High",
                "rationale": "The payment window is concentrated late in the month.",
                "recommended_action": "Confirm the client's payment execution needs.",
            }]
        }

        result = calculate_client_timing_intelligence(
            [ledger],
            reference_date="2026-08-20",
            gemini_client=gemini,
        )[0]

        self.assertEqual(result["engagement_prediction"]["generated_by"], "gemini")
        self.assertEqual(
            result["engagement_prediction"]["recommended_engagement_date"],
            "2026-08-22",
        )
        gemini.call_gemini_structured_json.assert_called_once()

    def test_clamps_day_to_short_month(self):
        self.assertEqual(
            next_occurrence_of_day(31, "2026-02-01").date().isoformat(),
            "2026-02-28",
        )

    def test_refresh_becomes_due_on_recommended_date_only_once_per_day(self):
        payload = {
            "generated_for_date": "2026-08-20",
            "clients": [{
                "engagement_prediction": {"recommended_engagement_date": "2026-08-22"},
                "payment_timing": {"predicted_payment_date": "2026-08-25"},
            }],
        }
        self.assertFalse(
            PipelineService._timing_refresh_due(payload, pd.Timestamp("2026-08-21"))
        )
        self.assertTrue(
            PipelineService._timing_refresh_due(payload, pd.Timestamp("2026-08-22"))
        )
        payload["generated_for_date"] = "2026-08-22"
        self.assertFalse(
            PipelineService._timing_refresh_due(payload, pd.Timestamp("2026-08-22"))
        )

    def test_missing_opportunity_scores_deduplicates_identical_sens_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PipelineService(directory)
            duplicate = {
                "company": "Example Ltd",
                "announcement_date": "2026-08-01",
                "title": "Results announcement",
                "source_document": "results.pdf",
                "transactional_banking_opportunity_score": None,
            }
            service.timing_path.parent.mkdir(parents=True, exist_ok=True)
            service.timing_path.with_name("current_sens_data.json").write_text(
                json.dumps([duplicate, duplicate]), encoding="utf-8"
            )

            missing = service._missing_opportunity_scores()

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["record_id"], service.opportunity_record_id(duplicate))

    def test_score_update_applies_to_all_duplicate_sens_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PipelineService(directory)
            duplicate = {
                "company": "Example Ltd",
                "announcement_date": "2026-08-01",
                "title": "Results announcement",
                "source_document": "results.pdf",
                "transactional_banking_opportunity_score": None,
            }
            external_path = service.json_dir / "current_external_data.json"
            sens_path = service.json_dir / "current_sens_data.json"
            external_path.write_text(json.dumps([{"company": "Example Ltd"}]), encoding="utf-8")
            sens_path.write_text(json.dumps([duplicate, duplicate]), encoding="utf-8")
            record_id = service.opportunity_record_id(duplicate)

            with patch.object(service, "aggregate", return_value=[]):
                service.update_opportunity_scores(
                    record_id,
                    {"transactional_banking_opportunity_score": 0.75},
                )
            saved = json.loads(sens_path.read_text(encoding="utf-8"))

        self.assertEqual(
            [row["transactional_banking_opportunity_score"] for row in saved],
            [0.75, 0.75],
        )

    def test_unscored_sens_count_requires_all_three_scores(self):
        sens = pd.DataFrame([
            {
                "transactional_banking_opportunity_score": 0.5,
                "global_markets_opportunity_score": 0.4,
                "investment_banking_opportunity_score": 0.3,
            },
            {
                "transactional_banking_opportunity_score": 0.5,
                "global_markets_opportunity_score": None,
                "investment_banking_opportunity_score": 0.3,
            },
        ])
        self.assertEqual(PipelineService._unscored_sens_row_count(sens), 1)
        self.assertEqual(
            PipelineService._unscored_sens_row_count(
                sens.drop(columns=["global_markets_opportunity_score"])
            ),
            2,
        )

    def test_pipeline_scores_unscored_sens_before_aggregation(self):
        external = pd.DataFrame([{"company": "Example Ltd"}])
        unscored = pd.DataFrame([{"company": "Example Ltd"}])
        scored = unscored.assign(
            transactional_banking_opportunity_score=0.5,
            global_markets_opportunity_score=0.4,
            investment_banking_opportunity_score=0.3,
        )
        with tempfile.TemporaryDirectory() as directory:
            service = PipelineService(directory)
            with patch(
                "backend.scripts.pipeline_service.DataCollector"
            ), patch(
                "backend.scripts.pipeline_service.Data_Processor"
            ) as processor_class, patch.dict(
                os.environ, {"GEMINI_API_KEY": "configured"}
            ), patch.object(
                service, "_is_standardized", return_value=True
            ), patch.object(
                service, "aggregate", return_value=[]
            ) as aggregate:
                processor = processor_class.return_value
                processor.prepare_incremental_data.return_value = (external, unscored)
                processor.process_new_data.return_value = (external, unscored, {})
                processor.last_extraction_status = {
                    "external_documents": set(),
                    "sens_documents": {"new-sens.pdf"},
                }
                processor.score_sens_opportunities.return_value = scored
                processor.validate_external_data.return_value = (external, scored)
                processor.standardize_data.return_value = (external, scored)

                status = service.run("sens")

        processor.score_sens_opportunities.assert_called_once_with(unscored)
        call_names = [call[0] for call in processor.method_calls]
        self.assertLess(
            call_names.index("score_sens_opportunities"),
            call_names.index("validate_external_data"),
        )
        aggregate.assert_called_once_with(external, scored)
        self.assertEqual(status["sens_scoring"]["state"], "complete")
        self.assertEqual(status["sens_scoring"]["rows_remaining"], 0)

    def test_pipeline_fails_instead_of_publishing_incomplete_sens_scores(self):
        external = pd.DataFrame([{"company": "Example Ltd"}])
        unscored = pd.DataFrame([{"company": "Example Ltd"}])
        with tempfile.TemporaryDirectory() as directory:
            service = PipelineService(directory)
            with patch(
                "backend.scripts.pipeline_service.DataCollector"
            ), patch(
                "backend.scripts.pipeline_service.Data_Processor"
            ) as processor_class, patch.dict(
                os.environ, {"GEMINI_API_KEY": "configured"}
            ), patch.object(
                service, "_is_standardized", return_value=True
            ), patch.object(
                service, "aggregate", return_value=[]
            ) as aggregate:
                processor = processor_class.return_value
                processor.prepare_incremental_data.return_value = (external, unscored)
                processor.process_new_data.return_value = (external, unscored, {})
                processor.last_extraction_status = {
                    "external_documents": set(),
                    "sens_documents": {"new-sens.pdf"},
                }
                processor.score_sens_opportunities.return_value = unscored

                with self.assertRaisesRegex(RuntimeError, "scoring was incomplete"):
                    service.run("sens")
                failed_status = service.status()

        aggregate.assert_not_called()
        self.assertEqual(failed_status["state"], "failed")
        self.assertEqual(failed_status["sens_scoring"]["state"], "failed")


if __name__ == "__main__":
    unittest.main()
