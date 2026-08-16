import unittest

from backend.prompts_briefing import (
    CLIENT_ID_PLACEHOLDER,
    CLIENT_NAME_PLACEHOLDER,
    MANAGER_ID_PLACEHOLDER,
    MANAGER_NAME_PLACEHOLDER,
    build_briefing_prompt,
    restore_briefing_placeholders,
)


class BriefingPromptPrivacyTests(unittest.TestCase):
    @staticmethod
    def client():
        return {
            "entity_id": "E-PRIVATE-01",
            "entity_name": "Private Client Ltd",
            "sector": "services",
            "estimated_total_wallet_zar": 1_000_000,
            "syn_bank_share_pct": 25.0,
            "wallet_gap_zar": 750_000,
            "opportunity_score": 80.0,
            "syn_txn_banking_pct": 40.0,
            "syn_global_markets_pct": 30.0,
            "syn_trade_finance_pct": 20.0,
            "lending_ib_pct": 10.0,
            "refinancing_flag": False,
            "import_mismatch_flag": False,
            "relationship_manager": {
                "employee_id": "RM-PRIVATE-01",
                "name": "Private Manager",
                "title": "Relationship Manager",
            },
        }

    def test_outbound_prompt_uses_placeholders_for_names_and_identifiers(self):
        prompt = build_briefing_prompt(self.client())

        for private_value in (
            "Private Client Ltd",
            "E-PRIVATE-01",
            "Private Manager",
            "RM-PRIVATE-01",
        ):
            self.assertNotIn(private_value, prompt)
        for placeholder in (
            CLIENT_NAME_PLACEHOLDER,
            CLIENT_ID_PLACEHOLDER,
            MANAGER_NAME_PLACEHOLDER,
            MANAGER_ID_PLACEHOLDER,
        ):
            self.assertIn(placeholder, prompt)

    def test_returned_placeholders_are_restored_locally(self):
        narrative = (
            f"{CLIENT_NAME_PLACEHOLDER} should contact "
            f"{MANAGER_NAME_PLACEHOLDER} ({MANAGER_ID_PLACEHOLDER}) about "
            f"client record {CLIENT_ID_PLACEHOLDER}."
        )

        restored = restore_briefing_placeholders(narrative, self.client())

        self.assertEqual(
            restored,
            "Private Client Ltd should contact Private Manager (RM-PRIVATE-01) "
            "about client record E-PRIVATE-01.",
        )
        self.assertNotIn("[[", restored)


if __name__ == "__main__":
    unittest.main()
