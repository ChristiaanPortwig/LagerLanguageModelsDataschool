"""
backend/prompts_briefing.py

Builds the prompt sent to Gemini for generating a client briefing note.
Used by backend/app.py once Gemini module is wired in.
"""

SYSTEM_INSTRUCTION = """You are an analyst assistant for Syn Bank, a corporate and 
investment bank. You write short, plain-English briefing notes for coverage bankers 
ahead of client meetings. Your notes are based on Syn Bank's internal transaction data 
and estimated wallet share — never invent facts not present in the data you're given.

Names and internal identifiers in the client data are represented by privacy placeholder
tokens. Never infer, expand, alter, or replace those tokens. If you refer to an identity,
copy its placeholder token exactly so the calling system can restore it locally.

Tone: professional, direct, confident. Written for a senior banker who is short on 
time — no filler, no restating the obvious, no hedging language like "it appears that" 
or "this may suggest."

Keep the note to 3 short paragraphs, in this order:
1. Relationship snapshot — one or two sentences on the client's size and Syn Bank's 
   current position with them.
2. The opportunity — the single most important flag or gap, stated plainly, with the 
   number that matters.
3. Recommended action — one concrete next step the banker should take, and why now.

Do not use headers, bullet points, or bold text. Write it as three flowing paragraphs
a banker could read aloud on a call. Do not include a greeting or sign-off.

Do not use any markdown syntax — no asterisks for bold, no hash symbols for headers,
no dashes or underscores as separators. Write plain prose only, as if speaking the
note aloud."""


# These opaque values are sent to Gemini in place of identifying client and employee
# data. They are deliberately stable so a returned narrative can be re-identified
# locally without disclosing the replacement map to the model provider.
CLIENT_NAME_PLACEHOLDER = "[[CLIENT_NAME]]"
CLIENT_ID_PLACEHOLDER = "[[CLIENT_ID]]"
MANAGER_NAME_PLACEHOLDER = "[[RELATIONSHIP_MANAGER_NAME]]"
MANAGER_ID_PLACEHOLDER = "[[RELATIONSHIP_MANAGER_ID]]"


def build_briefing_prompt(client: dict) -> str:
    """
    Takes a single client record (matching the shape returned by 
    GET /api/clients/:id) and returns the user-turn prompt to send to Gemini.
    """
    refinancing_line = (
        f"Refinancing flag: YES — window of {client['refinancing_window_days']} days."
        if client.get("refinancing_flag")
        else "Refinancing flag: no active signal."
    )
    mismatch_line = (
        "Import/trade finance mismatch: YES — client shows import activity not "
        "matched by trade finance business with Syn Bank."
        if client.get("import_mismatch_flag")
        else "Import/trade finance mismatch: none detected."
    )
    manager = client.get("relationship_manager", {}) or {}
    manager_line = (
        f"Relationship manager: {MANAGER_NAME_PLACEHOLDER}"
        f" ({manager.get('title', 'Relationship manager')}, "
        f"{MANAGER_ID_PLACEHOLDER})."
    )

    return f"""Write a briefing note for the following client, using only the data below.

Client: {CLIENT_NAME_PLACEHOLDER} ({CLIENT_ID_PLACEHOLDER})
Sector: {client['sector']}
{manager_line}
Estimated total banking wallet: R{client['estimated_total_wallet_zar']:,.0f}
Syn Bank's current share of wallet: {client['syn_bank_share_pct']:.1f}%
Estimated wallet gap (opportunity size): R{client['wallet_gap_zar']:,.0f}
Opportunity score (relative ranking across clients, higher = higher priority): {client['opportunity_score']:.1f}

Pillar breakdown (% of Syn Bank's observed activity with this client):
- Transactional Banking: {client['syn_txn_banking_pct']:.0f}%
- Global Markets / FX: {client['syn_global_markets_pct']:.0f}%
- Trade Finance: {client['syn_trade_finance_pct']:.0f}%
- Lending / Investment Banking: {client['lending_ib_pct']:.0f}%

{refinancing_line}
{mismatch_line}
"""


def restore_briefing_placeholders(narrative: str, client: dict) -> str:
    """Restore private identities in a Gemini narrative inside our trust boundary."""
    manager = client.get("relationship_manager", {}) or {}
    replacements = {
        CLIENT_NAME_PLACEHOLDER: str(client.get("entity_name") or "Unnamed client"),
        CLIENT_ID_PLACEHOLDER: str(client.get("entity_id") or "No client ID"),
        MANAGER_NAME_PLACEHOLDER: str(manager.get("name") or "Unassigned"),
        MANAGER_ID_PLACEHOLDER: str(manager.get("employee_id") or "No employee ID"),
    }
    restored = str(narrative)
    for placeholder, private_value in replacements.items():
        restored = restored.replace(placeholder, private_value)
    return restored


if __name__ == "__main__":
    # Quick manual test — paste the printed output into Google AI Studio
    # alongside SYSTEM_INSTRUCTION as the system prompt, to sanity-check
    # the output before Gemini module is ready.
    test_client = {
        "entity_id": "E11",
        "entity_name": "Pepkor Holdings",
        "sector": "consumer",
        "estimated_total_wallet_zar": 59_900_000_000,
        "syn_bank_share_pct": 19.0,
        "wallet_gap_zar": 48_519_000_000,
        "opportunity_score": 88.6,
        "syn_txn_banking_pct": 40,
        "syn_global_markets_pct": 20,
        "syn_trade_finance_pct": 30,
        "lending_ib_pct": 10,
        "refinancing_flag": False,
        "refinancing_window_days": None,
        "import_mismatch_flag": False,
    }
    print("=== SYSTEM INSTRUCTION ===")
    print(SYSTEM_INSTRUCTION)
    print("\n=== USER PROMPT ===")
    print(build_briefing_prompt(test_client))
