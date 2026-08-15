import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pandas as pd
from pypdf import PdfReader, PdfWriter

from backend.config.gemini_structured_schemas import (
    CompanyLevelExtDataCombinationResponse,
    SENSEventsResponse,
)
from backend.scripts.data_processing import Data_Processor


class DataProcessorTests(unittest.TestCase):
    @staticmethod
    def write_blank_pdf(path):
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as output_file:
            writer.write(output_file)
        writer.close()

    def test_non_sens_documents_are_sent_to_gemini_separately(self):
        processor = Data_Processor()

        with tempfile.TemporaryDirectory() as directory:
            company_dir = Path(directory) / "Example_Company"
            sens_dir = company_dir / "SENS"
            sens_dir.mkdir(parents=True)
            first_document = company_dir / "2024-report.pdf"
            second_document = company_dir / "2025-report.pdf"
            self.write_blank_pdf(first_document)
            self.write_blank_pdf(second_document)
            self.write_blank_pdf(sens_dir / "first-announcement.pdf")
            self.write_blank_pdf(sens_dir / "second-announcement.pdf")

            responses = iter([
                {
                    "records": [{
                        "company": "Example Company",
                        "report_date": "2024-12-31",
                        "revenue": 100,
                    }]
                },
                {
                    "records": [{
                        "company": "Example Company",
                        "report_date": "2025-12-31",
                        "revenue": 120,
                    }]
                },
                {"events": []},
                {
                    "record": {
                        "company": "Example Company",
                        "report_date": "2025-12-31",
                        "reporting_period_type": "annual",
                        "revenue": 120,
                    }
                },
            ])
            merged_sens_page_counts = []

            def gemini_response(schema, _prompt, pdf_source):
                if schema is SENSEventsResponse:
                    merged_sens_page_counts.append(
                        len(PdfReader(pdf_source).pages)
                    )
                return next(responses)

            with patch.object(
                processor.gemini_client,
                "call_gemini_structured_json",
                side_effect=gemini_response,
            ) as gemini_call, patch(
                "backend.scripts.data_processing.time.sleep"
            ) as sleep:
                company_df, _ = processor.extract_external_data_from_pdfs(
                    directory
                )

        calls = gemini_call.call_args_list
        self.assertEqual(calls[0].args[2], first_document)
        self.assertEqual(calls[1].args[2], second_document)
        self.assertEqual(
            calls[2].args[2].name,
            "Example_Company__SENS_merged.pdf",
        )
        self.assertIs(calls[3].args[0], CompanyLevelExtDataCombinationResponse)
        self.assertIsNone(calls[3].args[2])
        self.assertIn('"report_date":"2024-12-31"', calls[3].args[1])
        self.assertIn('"report_date":"2025-12-31"', calls[3].args[1])
        self.assertIn('"source_document":"2024-report.pdf"', calls[3].args[1])
        self.assertIn('"source_document":"2025-report.pdf"', calls[3].args[1])
        self.assertEqual(merged_sens_page_counts, [2])
        self.assertEqual(sleep.call_args_list, [
            call(10),
            call(10),
            call(10),
            call(10),
        ])
        self.assertEqual(len(company_df), 1)
        self.assertEqual(company_df.iloc[0]["revenue"], 120)

    def test_failed_request_waits_one_minute_before_retrying(self):
        processor = Data_Processor()
        expected = {"records": []}

        with patch.object(
            processor.gemini_client,
            "call_gemini_structured_json",
            side_effect=[RuntimeError("temporary failure"), expected],
        ) as gemini_call, patch(
            "backend.scripts.data_processing.time.sleep"
        ) as sleep:
            result = processor._call_gemini_with_retry(
                object(), "prompt", Path("report.pdf")
            )

        self.assertIs(result, expected)
        self.assertEqual(gemini_call.call_count, 2)
        self.assertEqual(sleep.call_args_list, [
            call(60),
            call(10),
        ])

    def test_request_is_skipped_after_more_than_two_failures(self):
        processor = Data_Processor()

        with patch.object(
            processor.gemini_client,
            "call_gemini_structured_json",
            side_effect=RuntimeError("permanent failure"),
        ) as gemini_call, patch(
            "backend.scripts.data_processing.time.sleep"
        ) as sleep:
            result = processor._call_gemini_with_retry(
                object(), "prompt", Path("report.pdf")
            )

        self.assertIsNone(result)
        self.assertEqual(gemini_call.call_count, 3)
        self.assertEqual(
            sleep.call_args_list,
            [call(60), call(60), call(60)],
        )

    def test_processing_continues_with_next_pdf_after_three_failures(self):
        processor = Data_Processor()

        with tempfile.TemporaryDirectory() as directory:
            company_dir = Path(directory) / "Example_Company"
            company_dir.mkdir()
            failed_document = company_dir / "1-failed.pdf"
            next_document = company_dir / "2-next.pdf"
            self.write_blank_pdf(failed_document)
            self.write_blank_pdf(next_document)

            with patch.object(
                processor.gemini_client,
                "call_gemini_structured_json",
                side_effect=[
                    RuntimeError("failure 1"),
                    RuntimeError("failure 2"),
                    RuntimeError("failure 3"),
                    {
                        "records": [{
                            "company": "Example Company",
                            "report_date": "2025-12-31",
                            "revenue": 120,
                        }]
                    },
                    {
                        "record": {
                            "company": "Example Company",
                            "report_date": "2025-12-31",
                            "reporting_period_type": "annual",
                            "revenue": 120,
                        }
                    },
                ],
            ) as gemini_call, patch(
                "backend.scripts.data_processing.time.sleep"
            ):
                company_df, sens_df = (
                    processor.extract_external_data_from_pdfs(directory)
                )

        requested_paths = [item.args[2] for item in gemini_call.call_args_list]
        self.assertEqual(
            requested_paths,
            [
                failed_document,
                failed_document,
                failed_document,
                next_document,
                None,
            ],
        )
        self.assertEqual(company_df.iloc[0]["revenue"], 120)
        self.assertTrue(sens_df.empty)

    def test_final_gemini_batch_reconciles_candidates_without_mechanical_merge(self):
        processor = Data_Processor()
        candidates = [
            {
                "company": "Example Company",
                "report_date": "2024-12-31",
                "revenue": 100,
                "employee_count": 50,
                "reporting_period_type": "annual",
            },
            {
                "company": "Example Company",
                "report_date": "2025-06-30",
                "revenue": 80,
                "employee_count": 75,
                "reporting_period_type": "interim",
            },
        ]

        with patch.object(
            processor.gemini_client,
            "call_gemini_structured_json",
            return_value={
                "record": {
                    "company": "Example Company",
                    "report_date": "2024-12-31",
                    "reporting_period_type": "annual",
                    "revenue": 100,
                    "employee_count": 50,
                }
            },
        ) as gemini_call, patch(
            "backend.scripts.data_processing.time.sleep"
        ):
            combined = processor._combine_company_records_with_gemini(
                candidates
            )

        self.assertEqual(combined[0]["report_date"], "2024-12-31")
        self.assertEqual(combined[0]["revenue"], 100)
        self.assertEqual(combined[0]["employee_count"], 50)
        schema, prompt, pdf_source = gemini_call.call_args.args
        self.assertIs(schema, CompanyLevelExtDataCombinationResponse)
        self.assertIsNone(pdf_source)
        self.assertIn('"reporting_period_type":"interim"', prompt)
        self.assertIn("Never fill a missing field", prompt)

    def test_final_gemini_batch_rejects_non_annual_output(self):
        processor = Data_Processor()
        with patch.object(
            processor.gemini_client,
            "call_gemini_structured_json",
            return_value={
                "record": {
                    "company": "Example Company",
                    "report_date": "2025-06-30",
                    "reporting_period_type": "interim",
                    "revenue": 80,
                }
            },
        ), patch("backend.scripts.data_processing.time.sleep"):
            combined = processor._combine_company_records_with_gemini([{
                "company": "Example Company",
                "report_date": "2025-06-30",
                "reporting_period_type": "interim",
                "revenue": 80,
            }])

        self.assertEqual(combined, [])

    def test_yfinance_fills_missing_values_and_replaces_mismatches(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame([{
            "company": "Glencore plc",
            "event_type": "acquisition",
            "event_value": 50,
        }])
        expenditure_df = pd.DataFrame([{
            "company": "Glencore plc",
            "report_date": "2025-12-31",
            "reporting_currency": "USD",
            "reporting_unit": "units",
            "revenue": 90_000_000,
            "cost_of_sales": None,
            "total_debt": None,
            "capital_expenditure": 5_000_000,
            "market_capitalisation": None,
            "share_price": 10,
        }])

        ticker = MagicMock()
        ticker.info = {
            "financialCurrency": "USD",
            "marketCap": 500_000_000,
            "currentPrice": 125,
            "enterpriseValue": 550_000_000,
            "fullTimeEmployees": 10_000,
        }
        statement_date = pd.Timestamp("2025-12-31")
        ticker.get_income_stmt.return_value = pd.DataFrame(
            {statement_date: [100_000_000, 40_000_000]},
            index=["Total Revenue", "Cost Of Revenue"],
        )
        ticker.get_balance_sheet.return_value = pd.DataFrame(
            {statement_date: [25_000_000]},
            index=["Total Debt"],
        )
        ticker.get_cash_flow.return_value = pd.DataFrame(
            {statement_date: [-6_000_000]},
            index=["Capital Expenditure"],
        )

        with patch(
            "backend.scripts.data_processing.yf.Ticker",
            return_value=ticker,
        ) as yfinance_ticker, self.assertLogs(
            "backend.scripts.data_processing", level="WARNING"
        ) as logs:
            validated_expenditure, validated_sens = (
                processor.validate_external_data(expenditure_df, sens_df)
            )

        pd.testing.assert_frame_equal(validated_sens, sens_df)
        yfinance_ticker.assert_called_once_with("GLN.JO")
        self.assertEqual(validated_expenditure.iloc[0]["revenue"], 100_000_000)
        self.assertEqual(
            validated_expenditure.iloc[0]["original_currency"], "USD"
        )
        self.assertEqual(
            validated_expenditure.iloc[0]["cost_of_sales"], 40_000_000
        )
        self.assertEqual(validated_expenditure.iloc[0]["total_debt"], 25_000_000)
        self.assertEqual(
            validated_expenditure.iloc[0]["capital_expenditure"], 6_000_000
        )
        self.assertEqual(
            validated_expenditure.iloc[0]["market_capitalisation"],
            500_000_000,
        )
        self.assertEqual(validated_expenditure.iloc[0]["share_price"], 125)
        self.assertEqual(
            validated_expenditure.iloc[0]["enterprise_value"],
            550_000_000,
        )
        self.assertEqual(
            validated_expenditure.iloc[0]["employee_count"], 10_000
        )
        self.assertIn("revenue differs", "\n".join(logs.output))
        self.assertIn("share_price differs", "\n".join(logs.output))

    def test_yfinance_fills_all_supported_missing_fields(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame()
        expenditure_df = pd.DataFrame([{
            "company": "Glencore plc",
            "report_date": "2025-12-31",
            "reporting_currency": "USD",
            "reporting_unit": "units",
            "foreign_revenue": pd.NA,
            "employee_expenses": float("nan"),
            "share_return": "",
            "ownership_major_shareholders": [],
        }])

        statement_date = pd.Timestamp("2025-12-31")
        ticker = MagicMock()
        ticker.info = {
            "financialCurrency": "USD",
            "assetsUnderManagement": 1_000_000_000,
            "fullTimeEmployees": 10_000,
        }
        ticker.fast_info = {
            "market_cap": 2_000_000_000,
            "last_price": 123,
            "year_change": 0.25,
        }
        ticker.get_income_stmt.return_value = pd.DataFrame(
            {statement_date: [100_000_000, -50_000_000, -10_000_000]},
            index=["Total Revenue", "Cost Of Revenue", "Salaries And Wages"],
        )
        ticker.get_balance_sheet.return_value = pd.DataFrame(
            {statement_date: [20_000_000, 10_000_000, 15_000_000, 5_000_000]},
            index=["Inventory", "Accounts Receivable", "Accounts Payable", "Current Debt"],
        )
        ticker.get_cash_flow.return_value = pd.DataFrame(
            {statement_date: [40_000_000]},
            index=["Foreign Sales"],
        )
        ticker.get_institutional_holders.return_value = pd.DataFrame({
            "Holder": ["Zulu Capital", "Alpha Investments"],
        })
        ticker.get_mutualfund_holders.return_value = pd.DataFrame({
            "Holder": ["Alpha Investments", "Beta Fund"],
        })

        with patch(
            "backend.scripts.data_processing.yf.Ticker",
            return_value=ticker,
        ):
            validated, _ = processor.validate_external_data(
                expenditure_df, sens_df
            )

        row = validated.iloc[0]
        self.assertEqual(row["foreign_revenue"], 40_000_000)
        self.assertEqual(row["employee_expenses"], 10_000_000)
        self.assertEqual(row["short_term_debt"], 5_000_000)
        self.assertEqual(row["debt_due_within_12_months"], 5_000_000)
        self.assertEqual(row["market_capitalisation"], 2_000_000_000)
        self.assertEqual(row["share_price"], 123)
        self.assertEqual(row["share_return"], 0.25)
        self.assertEqual(row["assets_under_management"], 1_000_000_000)
        self.assertEqual(row["receivable_days"], 36.5)
        self.assertEqual(row["payable_days"], 109.5)
        self.assertEqual(row["inventory_days"], 146)
        self.assertEqual(row["cash_conversion_cycle"], 73)
        self.assertEqual(
            row["ownership_major_shareholders"],
            ["Alpha Investments", "Beta Fund", "Zulu Capital"],
        )

        ticker.get_income_stmt.assert_has_calls([
            call(freq="yearly"),
            call(freq="quarterly"),
        ])

    def test_yfinance_skips_companies_without_a_jse_name(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame()
        expenditure_df = pd.DataFrame([{
            "company": "Unknown Company",
            "revenue": 100,
        }])

        with patch(
            "backend.scripts.data_processing.yf.Ticker"
        ) as yfinance_ticker, self.assertLogs(
            "backend.scripts.data_processing", level="WARNING"
        ):
            validated_expenditure, validated_sens = (
                processor.validate_external_data(expenditure_df, sens_df)
            )

        yfinance_ticker.assert_not_called()
        pd.testing.assert_frame_equal(validated_sens, sens_df)
        pd.testing.assert_frame_equal(validated_expenditure, expenditure_df)

    def test_validation_rejects_reversed_dataframes(self):
        processor = Data_Processor()
        external_df = pd.DataFrame([{
            "company": "Glencore",
            "reporting_currency": "USD",
            "reporting_unit": "units",
            "revenue": 1.0e8,
        }])
        sens_df = pd.DataFrame([{
            "company": "Glencore",
            "event_value": 1.0e6,
            "event_unit": "units",
            "currency": "USD",
        }])

        with self.assertRaisesRegex(ValueError, "appear to be reversed"):
            processor.validate_external_data(sens_df, external_df)

    def test_validation_rejects_legacy_scaled_values(self):
        processor = Data_Processor()
        external_df = pd.DataFrame([{
            "company": "Glencore",
            "reporting_currency": "USD",
            "reporting_unit": "millions",
            "revenue": 100,
        }])

        with self.assertRaisesRegex(ValueError, "base 'units'"):
            processor.validate_external_data(external_df, pd.DataFrame())

    def test_extraction_normalizes_gemini_output_to_stable_codes(self):
        processor = Data_Processor()

        with tempfile.TemporaryDirectory() as directory:
            company_dir = Path(directory) / "Glencore"
            sens_dir = company_dir / "SENS"
            sens_dir.mkdir(parents=True)
            report = company_dir / "report.pdf"
            announcement = sens_dir / "announcement.pdf"
            self.write_blank_pdf(report)
            self.write_blank_pdf(announcement)

            responses = [
                {
                    "records": [{
                        "company": "Glencore plc",
                        "report_date": "31-12-2025",
                        "reporting_currency": "US dollars",
                        "reporting_unit": "units",
                        "revenue": 1.25e9,
                        "countries_of_operation": [
                            "South Africa",
                            "United States",
                            "South Africa",
                        ],
                        "currencies_exposed_to": ["rand", "usd", "USD"],
                    }]
                },
                {
                    "events": [{
                        "company": "Glencore plc",
                        "announcement_date": "31-12-2025",
                        "event_type": "acquisition",
                        "event_value": 2.0e6,
                        "event_unit": "units",
                        "currency": "pound sterling",
                        "country": "United Kingdom",
                    }]
                },
                {
                    "record": {
                        "company": "Glencore plc",
                        "report_date": "31-12-2025",
                        "reporting_period_type": "annual",
                        "reporting_currency": "US dollars",
                        "reporting_unit": "units",
                        "revenue": 1.25e9,
                        "countries_of_operation": [
                            "South Africa",
                            "United States",
                            "South Africa",
                        ],
                        "currencies_exposed_to": ["rand", "usd", "USD"],
                    }
                },
            ]

            with patch.object(
                processor.gemini_client,
                "call_gemini_structured_json",
                side_effect=responses,
            ) as gemini_call, patch(
                "backend.scripts.data_processing.time.sleep"
            ):
                external_df, sens_df = processor.extract_external_data_from_pdfs(
                    directory
                )

        self.assertIn("`Glencore`", gemini_call.call_args_list[0].args[1])
        self.assertIn("scientific notation", gemini_call.call_args_list[0].args[1])
        self.assertIn("base units", gemini_call.call_args_list[1].args[1])
        self.assertIn(
            "final company-level dataframe",
            gemini_call.call_args_list[2].args[1],
        )
        self.assertEqual(external_df.iloc[0]["company"], "Glencore")
        self.assertEqual(external_df.iloc[0]["report_date"], "2025-12-31")
        self.assertEqual(external_df.iloc[0]["reporting_currency"], "USD")
        self.assertEqual(external_df.iloc[0]["reporting_unit"], "units")
        self.assertEqual(external_df.iloc[0]["revenue"], 1.25e9)
        self.assertEqual(
            external_df.iloc[0]["countries_of_operation"], ["US", "ZA"]
        )
        self.assertEqual(
            external_df.iloc[0]["currencies_exposed_to"], ["USD", "ZAR"]
        )
        self.assertEqual(sens_df.iloc[0]["company"], "Glencore")
        self.assertEqual(sens_df.iloc[0]["event_unit"], "units")
        self.assertEqual(sens_df.iloc[0]["event_value"], 2.0e6)
        self.assertEqual(sens_df.iloc[0]["currency"], "GBP")
        self.assertEqual(sens_df.iloc[0]["country"], "GB")

    def test_standardize_data_only_converts_both_frames_to_zar(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame([{
            "company": "Glencore plc",
            "announcement_date": "2025-01-10",
            "event_value": 4_000,
            "event_unit": "units",
            "currency": "GBP",
            "country": "United Kingdom",
            "banking_opportunities": "['fx', 'payments']",
        }])
        external_df = pd.DataFrame([{
            "company": "Glencore plc",
            "report_date": "2025-01-10",
            "reporting_currency": "USD",
            "reporting_unit": "units",
            "revenue": 2_000_000,
            "share_price": 3,
            "employee_count": 10,
            "countries_of_operation": ["South Africa"],
            "currencies_exposed_to": ["rand", "usd"],
        }])
        for column in ("countries_of_operation", "currencies_exposed_to"):
            external_df[column] = external_df[column].astype("string")
        sens_df["banking_opportunities"] = sens_df[
            "banking_opportunities"
        ].astype("string")

        def ticker_for(symbol):
            ticker = MagicMock()
            rate = {"USDZAR=X": 18.0, "GBPZAR=X": 23.0}[symbol]
            ticker.history.return_value = pd.DataFrame(
                {"Close": [rate]},
                index=[pd.Timestamp("2025-01-10")],
            )
            return ticker

        with patch(
            "backend.scripts.data_processing.yf.Ticker",
            side_effect=ticker_for,
        ) as yfinance_ticker:
            standardized_external, standardized_sens = (
                processor.standardize_data(external_df, sens_df)
            )
            repeated_external, repeated_sens = processor.standardize_data(
                standardized_external, standardized_sens
            )

        self.assertEqual(
            yfinance_ticker.call_args_list,
            [call("USDZAR=X"), call("GBPZAR=X")],
        )
        external_row = standardized_external.iloc[0]
        self.assertEqual(external_row["company"], "Glencore plc")
        self.assertEqual(external_row["reporting_unit"], "units")
        self.assertEqual(external_row["reporting_currency"], "ZAR")
        self.assertEqual(external_row["original_currency"], "USD")
        self.assertEqual(external_row["revenue"], 36_000_000)
        self.assertEqual(external_row["share_price"], 54)
        self.assertEqual(external_row["employee_count"], 10)
        self.assertEqual(external_row["countries_of_operation"], "['South Africa']")
        self.assertEqual(external_row["currencies_exposed_to"], "['rand', 'usd']")
        self.assertEqual(external_row["fx_rate_to_zar"], 18)
        self.assertEqual(external_row["fx_rate_date"], "2025-01-10")

        sens_row = standardized_sens.iloc[0]
        self.assertEqual(sens_row["company"], "Glencore plc")
        self.assertEqual(sens_row["event_unit"], "units")
        self.assertEqual(sens_row["currency"], "ZAR")
        self.assertEqual(sens_row["original_currency"], "GBP")
        self.assertEqual(sens_row["event_value"], 92_000)
        self.assertEqual(sens_row["country"], "United Kingdom")
        self.assertEqual(sens_row["banking_opportunities"], "['fx', 'payments']")
        self.assertEqual(sens_row["fx_rate_to_zar"], 23)
        self.assertEqual(sens_row["fx_rate_date"], "2025-01-10")

        pd.testing.assert_frame_equal(repeated_external, standardized_external)
        pd.testing.assert_frame_equal(repeated_sens, standardized_sens)

        self.assertEqual(external_df.iloc[0]["revenue"], 2_000_000)
        self.assertEqual(sens_df.iloc[0]["event_value"], 4_000)

    def test_standardize_data_leaves_unit_zar_values_unchanged(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame([{
            "announcement_date": "2025-01-10",
            "event_value": 2_000_000,
            "event_unit": "units",
            "currency": "rand",
        }])
        external_df = pd.DataFrame([{
            "report_date": "2025-01-10",
            "reporting_currency": "ZAR",
            "reporting_unit": "units",
            "total_debt": 3_000,
        }])

        with patch(
            "backend.scripts.data_processing.yf.Ticker"
        ) as yfinance_ticker:
            standardized_external, standardized_sens = (
                processor.standardize_data(external_df, sens_df)
            )

        yfinance_ticker.assert_not_called()
        self.assertEqual(standardized_sens.iloc[0]["event_value"], 2_000_000)
        self.assertEqual(standardized_sens.iloc[0]["currency"], "ZAR")
        self.assertEqual(
            standardized_sens.iloc[0]["original_currency"], "ZAR"
        )
        self.assertEqual(standardized_external.iloc[0]["total_debt"], 3_000)
        self.assertEqual(
            standardized_external.iloc[0]["reporting_currency"], "ZAR"
        )
        self.assertEqual(
            standardized_external.iloc[0]["original_currency"], "ZAR"
        )

    def test_standardize_data_rejects_legacy_scaled_values(self):
        processor = Data_Processor()
        external_df = pd.DataFrame([{
            "reporting_currency": "USD",
            "reporting_unit": "millions",
            "revenue": 2,
        }])

        with self.assertRaisesRegex(ValueError, "base 'units'"):
            processor.standardize_data(external_df, pd.DataFrame())

    def test_validation_keeps_standardized_values_in_zar(self):
        processor = Data_Processor()
        sens_df = pd.DataFrame([{
            "currency": "ZAR",
            "original_currency": "GBP",
            "event_value": 92_000,
        }])
        external_df = pd.DataFrame([{
            "company": "Glencore",
            "report_date": "2025-12-31",
            "reporting_currency": "ZAR",
            "original_currency": "USD",
            "reporting_unit": "units",
            "fx_rate_to_zar": 18.0,
            "fx_rate_date": "2025-12-31",
            "revenue": 1_620_000_000,
            "market_capitalisation": None,
        }])

        ticker = MagicMock()
        ticker.info = {
            "financialCurrency": "USD",
            "marketCap": 500_000_000,
        }
        statement_date = pd.Timestamp("2025-12-31")
        ticker.get_income_stmt.return_value = pd.DataFrame(
            {statement_date: [100_000_000]},
            index=["Total Revenue"],
        )
        ticker.get_balance_sheet.return_value = pd.DataFrame()
        ticker.get_cash_flow.return_value = pd.DataFrame()

        with patch(
            "backend.scripts.data_processing.yf.Ticker",
            return_value=ticker,
        ):
            validated_external, validated_sens = (
                processor.validate_external_data(external_df, sens_df)
            )

        self.assertEqual(validated_sens.iloc[0]["currency"], "ZAR")
        self.assertEqual(
            validated_sens.iloc[0]["original_currency"], "GBP"
        )
        row = validated_external.iloc[0]
        self.assertEqual(row["reporting_currency"], "ZAR")
        self.assertEqual(row["original_currency"], "USD")
        self.assertEqual(row["revenue"], 1_800_000_000)
        self.assertEqual(row["market_capitalisation"], 9_000_000_000)
        self.assertEqual(row["fx_rate_to_zar"], 18)


class IncrementalDataProcessorTests(unittest.TestCase):
    class RecordingProcessor(Data_Processor):
        def __init__(self):
            super().__init__()
            self.batches = []

        def extract_external_data_from_pdfs(self, source_dir):
            pdf_paths = sorted(Path(source_dir).rglob("*.pdf"))
            paths = [
                path.relative_to(source_dir).as_posix()
                for path in pdf_paths
            ]
            self.batches.append(paths)
            is_sens = any("/SENS/" in f"/{path}" for path in paths)
            self.last_extraction_status = {
                "external_documents": (
                    set() if is_sens else {str(path.resolve()) for path in pdf_paths}
                ),
                "sens_documents": (
                    {str(path.resolve()) for path in pdf_paths} if is_sens else set()
                ),
            }
            if is_sens:
                return pd.DataFrame(), pd.DataFrame([{
                    "company": "Glencore",
                    "announcement_date": "2026-08-15",
                    "event_type": "bond issue",
                    "event_value": 20,
                }])
            return pd.DataFrame([{
                "company": "Glencore",
                "report_date": "2026-06-30",
                "revenue": 200,
            }]), pd.DataFrame()

    def test_reports_refresh_by_company_while_only_new_sens_is_processed(self):
        processor = self.RecordingProcessor()
        current_external = pd.DataFrame([{
            "company": "Glencore",
            "report_date": "2025-12-31",
            "revenue": 100,
        }])
        current_sens = pd.DataFrame([{
            "company": "Glencore",
            "announcement_date": "2026-01-01",
            "event_type": "acquisition",
            "event_value": 10,
        }])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "downloads"
            json_dir = root / "json"
            company = downloads / "Glencore"
            sens = company / "SENS"
            sens.mkdir(parents=True)
            (company / "old-report.pdf").write_bytes(b"old report")
            (sens / "old-sens.pdf").write_bytes(b"old sens")

            external, sens_data = processor.prepare_incremental_data(
                current_sens_data=current_sens,
                current_external_data=current_external,
                source_dir=downloads,
                json_location=json_dir,
            )
            (company / "new-report.pdf").write_bytes(b"new report")
            (sens / "new-sens.pdf").write_bytes(b"new sens")
            external, sens_data = processor.process_new_data(
                current_sens_data=sens_data,
                current_external_data=external,
                source_dir=downloads,
                json_location=json_dir,
            )

            self.assertEqual(processor.batches, [
                ["Glencore/new-report.pdf", "Glencore/old-report.pdf"],
                ["Glencore/SENS/new-sens.pdf"],
            ])
            self.assertEqual(external["revenue"].tolist(), [200])
            self.assertEqual(sens_data["event_value"].tolist(), [10, 20])
            state = json.loads(
                (json_dir / "processed_documents.json").read_text()
            )["documents"]
            self.assertEqual(set(state), {
                "Glencore/old-report.pdf",
                "Glencore/new-report.pdf",
                "Glencore/SENS/old-sens.pdf",
                "Glencore/SENS/new-sens.pdf",
            })

            processor.batches.clear()
            reloaded_external, reloaded_sens = processor.process_new_data(
                source_dir=downloads,
                json_location=json_dir,
            )
            self.assertEqual(processor.batches, [])
            self.assertEqual(reloaded_external["revenue"].tolist(), [200])
            self.assertEqual(reloaded_sens["event_value"].tolist(), [10, 20])

    def test_sens_scope_ignores_untracked_external_documents(self):
        processor = self.RecordingProcessor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "downloads"
            json_dir = root / "json"
            company = downloads / "Glencore"
            company.mkdir(parents=True)
            (company / "untracked-report.pdf").write_bytes(b"report")

            external, sens_data = processor.process_new_data(
                source_dir=downloads,
                json_location=json_dir,
                process_scope="sens",
            )

        self.assertEqual(processor.batches, [])
        self.assertTrue(external.empty)
        self.assertTrue(sens_data.empty)


if __name__ == "__main__":
    unittest.main()
