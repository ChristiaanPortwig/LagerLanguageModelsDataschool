import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.scripts.wallet_size_pipeline import (
    _parse_args,
    run_wallet_size_pipeline,
)


class WalletSizePipelineTests(unittest.TestCase):
    def test_pipeline_collects_fills_standardizes_estimates_and_saves(self):
        raw_external = pd.DataFrame([{
            "company": "Example Ltd",
            "reporting_currency": "USD",
            "revenue": 100,
        }])
        raw_sens = pd.DataFrame([{
            "company": "Example Ltd",
            "event_type": "bond issue",
            "event_value": 10,
        }])
        filled_external = raw_external.assign(cost_of_sales=40)
        standardized_external = filled_external.assign(
            reporting_currency="ZAR", reporting_unit="units"
        )
        standardized_sens = raw_sens.assign(
            currency="ZAR", event_unit="units"
        )
        wallet_sizes = pd.DataFrame(
            {"total": [123]}, index=pd.Index(["Example Ltd"], name="company")
        )

        collector = MagicMock()
        processor = MagicMock()
        processor.prepare_incremental_data.return_value = (
            raw_external, raw_sens
        )
        processor.process_new_data.return_value = (
            raw_external, raw_sens
        )
        processor.validate_external_data.return_value = (
            filled_external, raw_sens
        )
        processor.standardize_data.return_value = (
            standardized_external, standardized_sens
        )

        with tempfile.TemporaryDirectory() as directory, patch(
            "backend.scripts.wallet_size_pipeline.calculate_total_wallet_size",
            return_value=wallet_sizes,
        ) as estimate:
            result = run_wallet_size_pipeline(
                scrape_scope="sens",
                json_dir=directory,
                fx_as_of_date="2026-08-15",
                collector=collector,
                processor=processor,
            )

            saved_wallets = json.loads(
                (Path(directory) / "wallet_sizes.json").read_text()
            )

        self.assertIs(result[0], standardized_external)
        self.assertIs(result[1], standardized_sens)
        self.assertIs(result[2], wallet_sizes)
        processor.prepare_incremental_data.assert_called_once_with(
            current_sens_data=None,
            current_external_data=None,
            source_dir=None,
            json_location=Path(directory),
        )
        collector.collect_data.assert_called_once_with(
            scrape_scope="sens",
            save_location=None,
        )
        processor.process_new_data.assert_called_once_with(
            current_sens_data=raw_sens,
            current_external_data=raw_external,
            source_dir=None,
            json_location=Path(directory),
            process_scope="sens",
        )
        processor.validate_external_data.assert_called_once_with(
            raw_external, raw_sens
        )
        processor.standardize_data.assert_called_once_with(
            filled_external,
            raw_sens,
            fx_as_of_date="2026-08-15",
        )
        estimate.assert_called_once_with(
            standardized_external, standardized_sens
        )
        processor.save_current_data.assert_called_once_with(
            standardized_external,
            standardized_sens,
            json_location=Path(directory),
        )
        self.assertEqual(saved_wallets, [{"company": "Example Ltd", "total": 123}])

    def test_cli_exposes_all_or_sens_scrape_scope(self):
        self.assertEqual(_parse_args([]).scrape, "all")
        self.assertEqual(_parse_args(["--scrape", "sens"]).scrape, "sens")


if __name__ == "__main__":
    unittest.main()
