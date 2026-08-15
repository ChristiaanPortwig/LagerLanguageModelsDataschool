import unittest

import pandas as pd

from backend.scripts.wallet_size import calculate_total_wallet_size


class WalletSizeTests(unittest.TestCase):
    def test_returns_pillars_total_and_confidence_by_company(self):
        companies = pd.DataFrame(
            [
                {
                    "company": "Example Ltd",
                    "report_date": "2025-12-31",
                    "reporting_unit": "units",
                    "revenue": 1_000,
                    "cost_of_sales": 400,
                    "employee_expenses": 100,
                    "tax_paid": 20,
                    "dividends_paid": 30,
                    "cash_and_cash_equivalents": 100,
                    "guarantees_outstanding": 25,
                    "fx_derivative_notional": 50,
                    "floating_rate_debt": 120,
                    "commodity_exposure_value": 80,
                    "bank_loan_debt": 150,
                    "project_or_contract_value": 200,
                }
            ]
        )

        result = calculate_total_wallet_size(companies)

        self.assertEqual(result.index.tolist(), ["Example Ltd"])
        self.assertEqual(result.loc["Example Ltd", "transactional_banking"], 2_075)
        self.assertEqual(result.loc["Example Ltd", "global_markets"], 250)
        self.assertEqual(result.loc["Example Ltd", "investment_banking"], 350)
        self.assertEqual(result.loc["Example Ltd", "total"], 2_675)
        self.assertEqual(
            result.loc["Example Ltd", "transactional_banking_confidence"], "low"
        )
        self.assertEqual(
            result.loc["Example Ltd", "global_markets_confidence"], "medium"
        )
        self.assertEqual(
            result.loc["Example Ltd", "investment_banking_confidence"], "low"
        )

    def test_failed_tiers_are_not_treated_as_zero(self):
        companies = pd.DataFrame(
            [
                {
                    "company": "Sparse Ltd",
                    "reporting_unit": "units",
                    "revenue": 100,
                }
            ]
        )

        with self.assertLogs(
            "backend.scripts.wallet_size", level="WARNING"
        ) as logs:
            result = calculate_total_wallet_size(companies).loc["Sparse Ltd"]

        self.assertEqual(result["transactional_banking"], 200)
        self.assertEqual(result["transactional_banking_confidence"], "low")
        self.assertTrue(pd.isna(result["global_markets"]))
        self.assertEqual(result["global_markets_confidence"], "can't estimate")
        self.assertTrue(pd.isna(result["investment_banking"]))
        self.assertEqual(result["investment_banking_confidence"], "can't estimate")
        self.assertTrue(pd.isna(result["total"]))
        message = "\n".join(logs.output)
        self.assertIn("transactional_banking confidence is low", message)
        self.assertIn("payments: Tier C proxy", message)
        self.assertIn("missing cost_of_sales, employee_expenses", message)
        self.assertIn("global_markets confidence is can't estimate", message)
        self.assertIn("interest_rate_derivative_notional", message)

    def test_optional_events_supply_direct_investment_banking_values(self):
        companies = pd.DataFrame(
            [
                {
                    "company": "Example Ltd",
                    "reporting_unit": "units",
                    "revenue": 100,
                    "foreign_revenue": 20,
                    "total_debt": 50,
                }
            ]
        )
        events = pd.DataFrame(
            [
                {
                    "company": "example ltd",
                    "event_type": "bond issue",
                    "event_value": 10,
                    "event_unit": "units",
                },
                {
                    "company": "Example Ltd",
                    "event_type": "rights issue",
                    "event_value": 20,
                    "event_unit": "units",
                },
                {
                    "company": "Example Ltd",
                    "event_type": "acquisition",
                    "event_value": 30,
                    "event_unit": "units",
                },
                {
                    "company": "Example Ltd",
                    "event_type": "project",
                    "event_value": 40,
                    "event_unit": "units",
                },
            ]
        )

        result = calculate_total_wallet_size(companies, events).loc["Example Ltd"]

        self.assertEqual(result["investment_banking"], 150)
        self.assertEqual(result["investment_banking_confidence"], "low")

    def test_rejects_unscaled_monetary_input(self):
        companies = pd.DataFrame(
            [
                {
                    "company": "Example Ltd",
                    "reporting_unit": "millions",
                    "revenue": 100,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "base 'units'"):
            calculate_total_wallet_size(companies)


if __name__ == "__main__":
    unittest.main()
