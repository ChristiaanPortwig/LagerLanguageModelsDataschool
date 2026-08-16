"""Client cash-cycle, payment-timing, and engagement intelligence.

This productionises the logic explored in ``notebooks/payment_cycles_timing.ipynb``.
The statistical cycle remains deterministic and auditable; Gemini uses that
evidence to recommend when and how a relationship manager should engage.
"""

from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backend.config.gemini_structured_schemas import (
    ClientEngagementPredictionsResponse,
)
from backend.scripts.gemini_client import Gemini_Client


LOGGER = logging.getLogger(__name__)
INFLOW_LABELS = frozenset({"credit", "inflow", "incoming", "in", "inbound", "export"})
OUTFLOW_LABELS = frozenset({"debit", "outflow", "outgoing", "out", "outbound", "import"})
WINDOW_DAYS = 3
DEFAULT_LEAD_DAYS = 30
HIGH_CONFIDENCE = 70.0
MEDIUM_CONFIDENCE = 45.0
STRATEGY_LEAD_DAYS = {
    "FX / Cross-Border": 30,
    "Liquidity Management": 14,
    "Trade Finance": 30,
    "Payments / Collections": 14,
    "General Coverage": DEFAULT_LEAD_DAYS,
}
STRATEGY_DESCRIPTIONS = {
    "FX / Cross-Border": (
        "Engage treasury about upcoming cross-border payments, FX execution, "
        "or hedging requirements."
    ),
    "Liquidity Management": (
        "Engage treasury about expected cash concentration, liquidity needs, "
        "or short-term funding."
    ),
    "Trade Finance": (
        "Engage about letters of credit, guarantees, collections, or trade-finance needs."
    ),
    "Payments / Collections": (
        "Engage about payment execution, collections, reconciliation, or transaction banking."
    ),
    "General Coverage": (
        "Use the predicted cash event as a reason for proactive relationship engagement."
    ),
}
LEDGERS = (
    ("transactional_banking.csv", "amount_zar", "transactional"),
    ("cross_border_payments.csv", "value_zar", "cross_border"),
    ("trade_finance.csv", "value_zar", "trade_finance"),
)


def load_payment_ledgers(data_dir: str | Path) -> list[pd.DataFrame]:
    """Load only the columns required for cycle analysis from all three ledgers."""
    root = Path(data_dir)
    frames = []
    for filename, value_column, source in LEDGERS:
        path = root / filename
        frame = pd.read_csv(
            path,
            usecols=["entity_id", "entity_name", "date", "direction", value_column],
        ).rename(columns={value_column: "value_zar"})
        frame["source"] = source
        frames.append(frame)
    return frames


def prepare_payment_data(ledgers: list[pd.DataFrame]) -> pd.DataFrame:
    """Normalise the notebook inputs into a single transaction stream."""
    if not ledgers:
        return pd.DataFrame(columns=[
            "entity_id", "entity_name", "date", "direction", "value_zar", "source",
            "day", "month",
        ])
    frame = pd.concat(ledgers, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value_zar"] = pd.to_numeric(frame["value_zar"], errors="coerce")
    frame["direction"] = frame["direction"].astype(str).str.casefold().str.strip()
    frame = frame.dropna(subset=["entity_id", "entity_name", "date", "value_zar"])
    frame = frame.loc[frame["value_zar"] > 0].copy()
    frame["day"] = frame["date"].dt.day
    frame["month"] = frame["date"].dt.month
    return frame


def confidence_band(confidence: float | None) -> str:
    if confidence is not None and confidence >= HIGH_CONFIDENCE:
        return "High"
    if confidence is not None and confidence >= MEDIUM_CONFIDENCE:
        return "Medium"
    return "Low"


def next_occurrence_of_day(day: int, reference_date: date | str | pd.Timestamp) -> pd.Timestamp:
    """Return the next valid occurrence of a day-of-month on or after reference_date."""
    reference = pd.Timestamp(reference_date).normalize()
    year, month = reference.year, reference.month
    while True:
        valid_day = min(int(day), calendar.monthrange(year, month)[1])
        candidate = pd.Timestamp(year=year, month=month, day=valid_day)
        if candidate >= reference:
            return candidate
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def _timing_window(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {
            "peak_day": None,
            "window_start_day": None,
            "window_end_day": None,
            "confidence_pct": None,
            "average_value_zar": None,
        }
    daily = rows.groupby("day")["value_zar"].sum().reindex(range(1, 32), fill_value=0.0)
    peak_day = int(daily.idxmax())
    window_start = max(1, peak_day - WINDOW_DAYS)
    window_end = min(31, peak_day + WINDOW_DAYS)
    total = float(daily.sum())
    confidence = 100.0 * float(daily.loc[window_start:window_end].sum()) / total
    return {
        "peak_day": peak_day,
        "window_start_day": window_start,
        "window_end_day": window_end,
        "confidence_pct": round(confidence, 2),
        "average_value_zar": round(float(rows["value_zar"].mean()), 2),
    }


def _choose_strategy(client: pd.DataFrame) -> str:
    outgoing = client.loc[client["direction"].isin(OUTFLOW_LABELS)]
    if outgoing.empty:
        return "General Coverage"
    totals = outgoing.groupby("source")["value_zar"].sum()
    if totals.empty:
        return "General Coverage"
    return {
        "cross_border": "FX / Cross-Border",
        "trade_finance": "Trade Finance",
        "transactional": "Payments / Collections",
    }.get(str(totals.idxmax()), "General Coverage")


def _monthly_cash_cycle(client: pd.DataFrame) -> list[dict[str, Any]]:
    signed = client.loc[client["direction"].isin(INFLOW_LABELS | OUTFLOW_LABELS)].copy()
    signed["signed_value"] = signed["value_zar"].where(
        signed["direction"].isin(INFLOW_LABELS), -signed["value_zar"]
    )
    monthly = signed.groupby("month")["signed_value"].mean().reindex(range(1, 13), fill_value=0.0)
    maximum = float(monthly.abs().max()) or 1.0
    return [
        {
            "month": month,
            "average_net_flow_zar": round(float(value), 2),
            "normalized_net_flow": round(float(value) / maximum, 4),
        }
        for month, value in monthly.items()
    ]


def _rules_engagement(payment: dict[str, Any], reference: pd.Timestamp) -> dict[str, Any]:
    if payment["predicted_payment_date"] is None:
        return {
            "recommended_engagement_date": None,
            "engage_now": False,
            "engagement_priority": "Low",
            "rationale": "No outgoing payment history is available to estimate an engagement date.",
            "recommended_action": STRATEGY_DESCRIPTIONS["General Coverage"],
            "generated_by": "rules_fallback",
        }
    recommended = pd.Timestamp(payment["rules_engagement_date"])
    predicted = pd.Timestamp(payment["predicted_payment_date"])
    engage_now = recommended <= reference <= predicted
    band = payment["confidence_band"]
    priority = "Immediate" if engage_now and band == "High" else band
    return {
        "recommended_engagement_date": max(reference, recommended).date().isoformat(),
        "engage_now": engage_now,
        "engagement_priority": priority,
        "rationale": (
            f"The strongest payment window is day {payment['window_start_day']}–"
            f"{payment['window_end_day']} with {payment['confidence_pct']:.2f}% historical "
            "value concentration."
        ),
        "recommended_action": payment["strategy_description"],
        "generated_by": "rules_fallback",
    }


def _base_client_timing(client: pd.DataFrame, reference: pd.Timestamp) -> dict[str, Any]:
    inflows = client.loc[client["direction"].isin(INFLOW_LABELS)]
    outflows = client.loc[client["direction"].isin(OUTFLOW_LABELS)]
    cash_in = _timing_window(inflows)
    cash_out = _timing_window(outflows)
    payment_window = _timing_window(outflows)
    strategy = _choose_strategy(client)
    lead_days = STRATEGY_LEAD_DAYS[strategy]

    if payment_window["peak_day"] is None:
        payment = {
            **payment_window,
            "predicted_payment_date": None,
            "expected_payment_value_zar": None,
            "confidence_band": "Low",
            "strategy": strategy,
            "lead_days": lead_days,
            "rules_engagement_date": None,
            "days_until_payment": None,
            "strategy_description": STRATEGY_DESCRIPTIONS[strategy],
            "daily_value_distribution": [],
        }
    else:
        predicted = next_occurrence_of_day(payment_window["peak_day"], reference)
        rules_date = predicted - pd.Timedelta(days=lead_days)
        window_rows = outflows.loc[outflows["day"].between(
            payment_window["window_start_day"], payment_window["window_end_day"]
        )]
        daily = outflows.groupby("day")["value_zar"].sum().reindex(range(1, 32), fill_value=0.0)
        total = float(daily.sum()) or 1.0
        payment = {
            **payment_window,
            "predicted_payment_date": predicted.date().isoformat(),
            "expected_payment_value_zar": round(float(window_rows["value_zar"].mean()), 2),
            "confidence_band": confidence_band(payment_window["confidence_pct"]),
            "strategy": strategy,
            "lead_days": lead_days,
            "rules_engagement_date": rules_date.date().isoformat(),
            "days_until_payment": int((predicted - reference).days),
            "strategy_description": STRATEGY_DESCRIPTIONS[strategy],
            "daily_value_distribution": [
                {"day": day, "proportion": round(float(value) / total, 6)}
                for day, value in daily.items()
            ],
        }

    entity_id = str(client["entity_id"].iloc[0])
    result = {
        "entity_id": entity_id,
        "entity_name": str(client["entity_name"].iloc[0]),
        "cash_cycle": {
            "cash_in": cash_in,
            "cash_out": cash_out,
            "monthly_net_flow": _monthly_cash_cycle(client),
        },
        "payment_timing": payment,
    }
    result["engagement_prediction"] = _rules_engagement(payment, reference)
    return result


def _gemini_prompt(records: list[dict[str, Any]], reference: pd.Timestamp) -> str:
    evidence = [
        {
            "entity_id": item["entity_id"],
            "entity_name": item["entity_name"],
            "payment_timing": {
                key: item["payment_timing"][key]
                for key in (
                    "predicted_payment_date", "window_start_day", "window_end_day",
                    "confidence_pct", "confidence_band", "expected_payment_value_zar",
                    "strategy", "lead_days", "rules_engagement_date",
                )
            },
            "cash_in": item["cash_cycle"]["cash_in"],
            "cash_out": item["cash_cycle"]["cash_out"],
        }
        for item in records
        if item["payment_timing"]["predicted_payment_date"]
    ]
    return (
        "You are a corporate-banking relationship planning assistant. Recommend when to "
        "engage each client using only the supplied historical cycle evidence. Return exactly "
        "one prediction per entity_id. The engagement date must be on or after the reference "
        "date and no later than the predicted payment date. Prefer the rules engagement date, "
        "but use today when that date has passed. Do not invent events or client facts. Make "
        "the action specific to the supplied product strategy.\n\n"
        f"Reference date: {reference.date().isoformat()}\n"
        f"Client timing evidence: {json.dumps(evidence, ensure_ascii=False)}"
    )


def apply_gemini_engagement_predictions(
    records: list[dict[str, Any]],
    reference_date: date | str | pd.Timestamp,
    gemini_client: Gemini_Client,
) -> list[dict[str, Any]]:
    """Add validated Gemini recommendations while retaining safe rule fallbacks."""
    reference = pd.Timestamp(reference_date).normalize()
    eligible = [row for row in records if row["payment_timing"]["predicted_payment_date"]]
    if not eligible:
        return records
    response = gemini_client.call_gemini_structured_json(
        ClientEngagementPredictionsResponse,
        _gemini_prompt(records, reference),
        pdfs_dir=None,
    )
    predictions = {
        str(item.get("entity_id")): item
        for item in response.get("predictions", [])
        if isinstance(item, dict)
    }
    for row in eligible:
        prediction = predictions.get(row["entity_id"])
        if not prediction:
            continue
        try:
            recommendation = pd.Timestamp(prediction["recommended_engagement_date"]).normalize()
            payment_date = pd.Timestamp(row["payment_timing"]["predicted_payment_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not reference <= recommendation <= payment_date:
            continue
        row["engagement_prediction"] = {
            "recommended_engagement_date": recommendation.date().isoformat(),
            "engage_now": recommendation <= reference,
            "engagement_priority": prediction["engagement_priority"],
            "rationale": prediction["rationale"].strip(),
            "recommended_action": prediction["recommended_action"].strip(),
            "generated_by": "gemini",
        }
    return records


def calculate_client_timing_intelligence(
    ledgers: list[pd.DataFrame],
    *,
    reference_date: date | str | pd.Timestamp | None = None,
    gemini_client: Gemini_Client | None = None,
) -> list[dict[str, Any]]:
    """Calculate all client cycles and optionally add Gemini recommendations."""
    reference = pd.Timestamp(reference_date or date.today()).normalize()
    transactions = prepare_payment_data(ledgers)
    records = [
        _base_client_timing(client, reference)
        for _, client in transactions.groupby("entity_id", sort=True)
    ]
    if gemini_client is not None:
        try:
            apply_gemini_engagement_predictions(records, reference, gemini_client)
        except Exception:
            LOGGER.exception("Gemini engagement prediction failed; retaining rules fallbacks")
    return records


def build_client_timing_intelligence(
    data_dir: str | Path,
    *,
    reference_date: date | str | pd.Timestamp | None = None,
    gemini_client: Gemini_Client | None = None,
    use_gemini: bool = True,
) -> list[dict[str, Any]]:
    """Load ledger files and return API-ready timing intelligence."""
    if use_gemini and gemini_client is None and os.getenv("GEMINI_API_KEY"):
        gemini_client = Gemini_Client()
    if not use_gemini:
        gemini_client = None
    return calculate_client_timing_intelligence(
        load_payment_ledgers(data_dir),
        reference_date=reference_date,
        gemini_client=gemini_client,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[2] / "data")
    parser.add_argument("--reference-date", help="ISO date used to schedule the next cycle")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--no-gemini", action="store_true", help="Use deterministic fallback only")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = None if args.no_gemini or not os.getenv("GEMINI_API_KEY") else Gemini_Client()
    records = build_client_timing_intelligence(
        args.data_dir,
        reference_date=args.reference_date,
        gemini_client=client,
        use_gemini=not args.no_gemini,
    )
    payload = json.dumps(records, indent=2, ensure_ascii=False, allow_nan=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
