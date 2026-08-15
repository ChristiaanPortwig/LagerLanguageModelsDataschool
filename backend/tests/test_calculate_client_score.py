import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from backend.scripts.calculate_client_score import calculate_client_score


class CalculateClientScoreTests(unittest.TestCase):
    def setUp(self):
        self.clients = pd.DataFrame(
            {
                "entity_id": ["A", "B"],
                "entity_name": ["Alpha", "Beta"],
                "txn_banking_total_zar": [100, 40],
                "cross_border_total_zar": [50, 100],
                "trade_finance_total_zar": [20, 10],
                "lending_signal_total_zar": [20, 0],
            }
        )
        self.sens = pd.DataFrame(
            {
                "company": ["Alpha", "Alpha", "Beta"],
                "transactional_banking_opportunity_score": [0.2, 0.3, 0.5],
                "global_markets_opportunity_score": [0.1, 0.3, 0.1],
                "investment_banking_opportunity_score": [0.05, 0.05, 0.4],
            }
        )
        self.wallets = pd.DataFrame(
            {
                "transactional_banking": [200, 150],
                "global_markets": [100, 200],
                "investment_banking": [100, 100],
            },
            index=pd.Index(["Alpha", "Beta"], name="company"),
        )

    def test_calculates_pillar_and_wallet_gap_weighted_total_scores(self):
        result = calculate_client_score(self.clients, self.sens, self.wallets)

        alpha = result.set_index("entity_name").loc["Alpha"]
        self.assertEqual(alpha["transactional_banking_captured_wallet"], 120)
        self.assertEqual(alpha["transactional_banking_wallet_gap"], 80)
        self.assertAlmostEqual(alpha["transactional_banking_gap_score"], 80 / 180)
        self.assertAlmostEqual(alpha["transactional_banking_raw_sens"], 0.5)
        self.assertAlmostEqual(alpha["transactional_banking_sens_score"], 0.5)
        self.assertAlmostEqual(
            alpha["transactional_banking_relationship_score"], 1.0
        )

        expected_transactional = 0.5 * (80 / 180) + 0.4 * 0.5 + 0.1
        self.assertAlmostEqual(
            alpha["transactional_banking_score"], expected_transactional
        )

        expected_global = 0.5 * (50 / 150) + 0.4 * 0.8 + 0.1 * 0.75
        expected_investment = 0.5 * (80 / 180) + 0.4 * 0.2 + 0.1
        expected_total = (
            80 * expected_transactional
            + 50 * expected_global
            + 80 * expected_investment
        ) / 210
        self.assertAlmostEqual(alpha["total_score"], expected_total)

    def test_does_not_modify_inputs(self):
        original_clients = self.clients.copy(deep=True)
        original_sens = self.sens.copy(deep=True)
        original_wallets = self.wallets.copy(deep=True)

        calculate_client_score(self.clients, self.sens, self.wallets)

        assert_frame_equal(self.clients, original_clients)
        assert_frame_equal(self.sens, original_sens)
        assert_frame_equal(self.wallets, original_wallets)

    def test_rejects_weights_that_do_not_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "weights must sum to 1"):
            calculate_client_score(
                self.clients,
                self.sens,
                self.wallets,
                gap_weight=0.5,
                sens_weight=0.5,
                relationship_weight=0.5,
            )


if __name__ == "__main__":
    unittest.main()
