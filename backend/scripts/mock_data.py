"""
mock_data.py

Generates fake but plausible share-of-wallet data for 20 corporate clients
(E01-E20) for a banking share-of-wallet dashboard, and writes it to
data/mock_clients.json so a future API endpoint can serve it directly.

Usage:
    python backend/scripts/mock_data.py
"""

import json
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEED = 42
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mock_clients.json"

# Real client names + sectors, in E01-E20 order.
CLIENTS = [
    ("E01", "BHP Group", "mining"),
    ("E02", "Glencore", "mining"),
    ("E03", "Anglo American", "mining"),
    ("E04", "AngloGold Ashanti", "mining"),
    ("E05", "Gold Fields", "mining"),
    ("E06", "Valterra Platinum", "mining"),
    ("E07", "OUTsurance Group", "insurance"),
    ("E08", "Sanlam", "insurance"),
    ("E09", "Shoprite Holdings", "consumer"),
    ("E10", "Bid Corporation", "consumer"),
    ("E11", "Pepkor Holdings", "consumer"),
    ("E12", "Clicks Group", "consumer"),
    ("E13", "NEPI Rockcastle", "real_estate"),
    ("E14", "Prosus", "tech"),
    ("E15", "Naspers", "tech"),
    ("E16", "MTN Group", "telecoms"),
    ("E17", "Vodacom Group", "telecoms"),
    ("E18", "The Bidvest Group", "industrials_pharma"),
    ("E19", "Aspen Pharmacare", "industrials_pharma"),
    ("E20", "Shaftesbury Capital plc", "real_estate"),
]

# Sector wallet-size multipliers: large miners and consumer groups skew
# higher, smaller/niche sectors skew lower. Applied as a range multiplier
# on top of the base R500M-R80B envelope.
SECTOR_WALLET_RANGE_ZAR = {
    "mining": (15_000_000_000, 80_000_000_000),
    "consumer": (8_000_000_000, 60_000_000_000),
    "telecoms": (10_000_000_000, 55_000_000_000),
    "tech": (5_000_000_000, 45_000_000_000),
    "industrials_pharma": (3_000_000_000, 30_000_000_000),
    "insurance": (2_000_000_000, 20_000_000_000),
    "real_estate": (500_000_000, 15_000_000_000),
}

REFINANCING_PROBABILITY = 0.30
IMPORT_MISMATCH_PROBABILITY = 0.25

PILLARS = ["txn_banking_pct", "cross_border_pct", "trade_finance_pct", "lending_ib_pct"]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_pillar_percentages(rng: random.Random) -> dict:
    """Four pillar percentages that sum to exactly 100."""
    # Dirichlet-style split via random cut points, then round to whole
    # percent while preserving the sum-to-100 constraint.
    weights = [rng.uniform(0.5, 2.0) for _ in PILLARS]
    total_weight = sum(weights)
    raw = [w / total_weight * 100 for w in weights]

    rounded = [int(x) for x in raw]
    remainder = 100 - sum(rounded)
    # Distribute the rounding remainder to the pillars with the largest
    # fractional parts so the total lands exactly on 100.
    fractional_order = sorted(
        range(len(PILLARS)), key=lambda i: raw[i] - rounded[i], reverse=True
    )
    for i in range(remainder):
        rounded[fractional_order[i]] += 1

    return dict(zip(PILLARS, rounded))


def generate_estimated_wallet(rng: random.Random, sector: str) -> float:
    lo, hi = SECTOR_WALLET_RANGE_ZAR[sector]
    return round(rng.uniform(lo, hi), 2)


def generate_bank_share(rng: random.Random) -> float:
    return round(rng.uniform(10.0, 75.0), 2)


def generate_refinancing(rng: random.Random) -> tuple:
    flag = rng.random() < REFINANCING_PROBABILITY
    window = rng.randint(1, 180) if flag else None
    return flag, window


def generate_import_mismatch(rng: random.Random) -> bool:
    return rng.random() < IMPORT_MISMATCH_PROBABILITY


def compute_opportunity_score(wallet_gap: float, all_gaps: list) -> float:
    """
    0-100 score weighted toward clients with a high wallet_gap_zar.
    Normalizes the gap against the full cohort's min/max, then adds a
    small amount of noise so scores aren't a perfectly linear readout
    of the gap alone.
    """
    min_gap, max_gap = min(all_gaps), max(all_gaps)
    if max_gap == min_gap:
        normalized = 0.5
    else:
        normalized = (wallet_gap - min_gap) / (max_gap - min_gap)
    return normalized


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rng = random.Random(SEED)

    records = []
    for entity_id, name, sector in CLIENTS:
        pillars = generate_pillar_percentages(rng)
        estimated_total_wallet_zar = generate_estimated_wallet(rng, sector)
        syn_bank_share_pct = generate_bank_share(rng)
        wallet_gap_zar = round(
            estimated_total_wallet_zar * (1 - syn_bank_share_pct / 100), 2
        )
        refinancing_flag, refinancing_window_days = generate_refinancing(rng)
        import_mismatch_flag = generate_import_mismatch(rng)

        record = {
            "entity_id": entity_id,
            "entity_name": name,
            "sector": sector,
            **pillars,
            "estimated_total_wallet_zar": estimated_total_wallet_zar,
            "syn_bank_share_pct": syn_bank_share_pct,
            "wallet_gap_zar": wallet_gap_zar,
            "refinancing_flag": refinancing_flag,
            "refinancing_window_days": refinancing_window_days,
            "import_mismatch_flag": import_mismatch_flag,
        }
        records.append(record)

    # opportunity_score depends on the full cohort's wallet_gap distribution,
    # so it's computed in a second pass once every gap is known.
    all_gaps = [r["wallet_gap_zar"] for r in records]
    for r in records:
        normalized_gap = compute_opportunity_score(r["wallet_gap_zar"], all_gaps)
        # Blend the gap-driven signal (85% weight) with a little randomness
        # (15% weight) so opportunity_score isn't a pure re-statement of
        # wallet_gap_zar, while still being clearly weighted toward it.
        noise = rng.uniform(0, 1)
        score = 0.85 * normalized_gap + 0.15 * noise
        r["opportunity_score"] = round(score * 100, 2)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(f"Wrote {len(records)} client records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
