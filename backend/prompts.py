"""
backend/prompts.py

Builds the prompt sent to Gemini for generating a client briefing note.
Used by backend/app.py once Gemini module is wired in.
"""

SYSTEM_INSTRUCTION = """You are an analyst assistant for Syn Bank, a corporate and 
investment bank. You write short, plain-English briefing notes for coverage bankers 
ahead of client meetings. Your notes are based on Syn Bank's internal transaction data 
and estimated wallet share — never invent facts not present in the data you're given.

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
a banker could read aloud on a call. Do not include a greeting or sign-off."""


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

    return f"""Write a briefing note for the following client, using only the data below.

Client: {client['entity_name']} ({client['entity_id']})
Sector: {client['sector']}
Estimated total banking wallet: R{client['estimated_total_wallet_zar']:,.0f}
Syn Bank's current share of wallet: {client['syn_bank_share_pct']:.1f}%
Estimated wallet gap (opportunity size): R{client['wallet_gap_zar']:,.0f}
Opportunity score (0-100, higher = higher priority): {client['opportunity_score']:.1f}

Pillar breakdown (% of Syn Bank's observed activity with this client):
- Transactional Banking: {client['txn_banking_pct']:.0f}%
- Cross Border / FX: {client['cross_border_pct']:.0f}%
- Trade Finance: {client['trade_finance_pct']:.0f}%
- Lending / Investment Banking: {client['lending_ib_pct']:.0f}%

{refinancing_line}
{mismatch_line}
"""


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
        "txn_banking_pct": 40,
        "cross_border_pct": 20,
        "trade_finance_pct": 30,
        "lending_ib_pct": 10,
        "refinancing_flag": False,
        "refinancing_window_days": None,
        "import_mismatch_flag": False,
    }
    print("=== SYSTEM INSTRUCTION ===")
    print(SYSTEM_INSTRUCTION)
    print("\n=== USER PROMPT ===")
    print(build_briefing_prompt(test_client))