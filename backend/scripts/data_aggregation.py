"""
 Core Aggregation Pipeline

This module contains function to deduplicate the datasets (by finding overlap) 
and then aggregates the ledgers to find the total captured cash by syn bank

Example Usage for API/Backend Route:
------------------------------------
# 1. Find overlapping cross-ledger settlements
overlap_df = find_cross_ledger_overlaps(
    cross_border_df=cross_border_payments, 
    transactional_df=transactional_banking,
    day_tolerance=3,
    amount_tolerance_pct=1.0
)
    
# 2. Build the deduplicated client wallet baseline
final_client_table = build_client_wallet_baseline(
    transactional_df=transactional_banking,
    cross_border_df=cross_border_payments,
    trade_finance_df=trade_finance,
    overlap_df=overlap_df
)
    
# 3. Convert to dictionary/JSON to send to frontend
dashboard_json = final_client_table.to_dict(orient='records')
"""

import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from backend.scripts.calculate_client_score import calculate_client_score
from backend.scripts.wallet_size import calculate_total_wallet_size


def find_cross_ledger_overlaps(
    cross_border_df: pd.DataFrame, 
    transactional_df: pd.DataFrame, 
    day_tolerance: int = 3, 
    amount_tolerance_pct: float = 1.0
) -> pd.DataFrame:
    """
    Identifies overlapping transactions between cross-border and transactional ledgers
    using a date-blocked fuzzy merge to account for settlement lag and FX/fee spreads.
    
    Args:
        cross_border_df: DataFrame containing cross-border payments.
        transactional_df: DataFrame containing transactional banking records.
        day_tolerance: Maximum days of settlement lag to check (e.g., 3 means -3 to +3).
        amount_tolerance_pct: Maximum allowable percentage difference in ZAR amounts.
        
    Returns:
        pd.DataFrame: A strict 1-to-1 mapping of overlapping transaction IDs.
    """
    cb = cross_border_df[['transaction_id', 'entity_id', 'date', 'value_zar', 'direction']].copy()
    tb = transactional_df[['transaction_id', 'entity_id', 'date', 'amount_zar', 'direction']].copy()

    cb['date'] = pd.to_datetime(cb['date'])
    tb['date'] = pd.to_datetime(tb['date'])

    matches_list = []

    # range(-day_tolerance, day_tolerance + 1) creates the dynamic offset window
    for day_offset in range(-day_tolerance, day_tolerance + 1):
        cb_shifted = cb.copy()
        cb_shifted['join_date'] = cb_shifted['date'] + pd.Timedelta(days=day_offset)
        
        tb_subset = tb.copy()
        tb_subset['join_date'] = tb_subset['date']
        
        # Inner merge on client, direction, and shifted date
        merged = pd.merge(
            cb_shifted,
            tb_subset,
            on=['entity_id', 'direction', 'join_date'],
            suffixes=('_cb', '_tb')
        )
        
        merged['amount_diff_pct'] = (
            (merged['value_zar'] - merged['amount_zar']).abs() / merged['value_zar']
        ) * 100
        
        matched = merged[merged['amount_diff_pct'] <= amount_tolerance_pct].copy()
        
        if not matched.empty:
            matched['day_diff'] = abs(day_offset)
            matches_list.append(matched)

    if matches_list:
        overlap_check = pd.concat(matches_list, ignore_index=True)
        
        # Sort by the smallest date difference, then the smallest ZAR amount variance
        overlap_check = overlap_check.sort_values(by=['day_diff', 'amount_diff_pct'])
        
        # Drop duplicates keeping only the FIRST (best) match for each ID
        overlap_check = overlap_check.drop_duplicates(subset=['transaction_id_cb'], keep='first')
        overlap_check = overlap_check.drop_duplicates(subset=['transaction_id_tb'], keep='first')
    else:
        # Fallback empty dataframe
        overlap_check = pd.DataFrame(columns=['transaction_id_cb', 'transaction_id_tb'])

    return overlap_check

def build_client_wallet_baseline(
    transactional_df: pd.DataFrame,
    cross_border_df: pd.DataFrame,
    trade_finance_df: pd.DataFrame,
    overlap_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Aggregates transactional, cross-border, and trade finance data into a consolidated 
    client master table. Deduplicates overlapping flows and extracts hidden lending signals.
    
    Args:
        transactional_df: Raw transactional banking dataframe.
        cross_border_df: Raw cross-border payments dataframe.
        trade_finance_df: Raw trade finance dataframe.
        overlap_df: Dataframe containing fuzzy-matched cross-ledger duplicate IDs.
        
    Returns:
        pd.DataFrame: A client-level summary of pure deduplicated cash flows.
    """
    
    clients = (
        transactional_df[['entity_id', 'entity_name', 'sector']]
        .drop_duplicates()
        .sort_values('entity_id')
        .reset_index(drop=True)
    )

    # Exclude "intercompany_sweeps" (internal treasury) and "memo" (hidden lending)
    tb_lending_mask = transactional_df['memo'].notna()
    tb_core = transactional_df[
        (transactional_df['leg_type'] != 'intercompany_sweeps') & 
        (~tb_lending_mask)
    ]
    tb_totals = (
        tb_core.groupby('entity_id')['amount_zar']
        .sum()
        .rename('txn_banking_total_zar')
    )

    # Extract the cross-border transaction IDs already accounted for in Transactional
    overlapping_cb_ids = set()
    if not overlap_df.empty and 'transaction_id_cb' in overlap_df.columns:
        overlapping_cb_ids = set(overlap_df['transaction_id_cb'].unique())

    # Exclude intercompany, memo-tagged rows, and overlapping duplicates
    cb_lending_mask = cross_border_df['memo'].notna()
    cb_core = cross_border_df[
        (cross_border_df['corridor_type'] != 'intercompany') & 
        (~cb_lending_mask) & 
        (~cross_border_df['transaction_id'].isin(overlapping_cb_ids))
    ]
    cb_totals = (
        cb_core.groupby('entity_id')['value_zar']
        .sum()
        .rename('cross_border_total_zar')
    )

    # Exclude memo-tagged rows
    tf_lending_mask = trade_finance_df['memo'].notna()
    tf_core = trade_finance_df[~tf_lending_mask]
    tf_totals = (
        tf_core.groupby('entity_id')['value_zar']
        .sum()
        .rename('trade_finance_total_zar')
    )

    # Combine the removed memo rows from all 3 datasets
    lending_parts = [
        transactional_df.loc[tb_lending_mask, ['entity_id', 'amount_zar']]
            .rename(columns={'amount_zar': 'value_zar'}),
        cross_border_df.loc[cb_lending_mask, ['entity_id', 'value_zar']],
        trade_finance_df.loc[tf_lending_mask, ['entity_id', 'value_zar']],
    ]
    lending_combined = pd.concat(lending_parts, ignore_index=True)

    lending_totals = (
        lending_combined.groupby('entity_id')['value_zar']
        .agg(
            lending_signal_total_zar='sum', 
            lending_signal_txn_count='count'
        )
    )

    client_table = (
        clients
        .merge(tb_totals, on='entity_id', how='left')
        .merge(cb_totals, on='entity_id', how='left')
        .merge(tf_totals, on='entity_id', how='left')
        .merge(lending_totals, on='entity_id', how='left')
    )

    value_cols = [
        'txn_banking_total_zar', 'cross_border_total_zar',
        'trade_finance_total_zar', 'lending_signal_total_zar', 'lending_signal_txn_count'
    ]
    client_table[value_cols] = client_table[value_cols].fillna(0)

    # Total deduplicated cash captured by Syn Bank
    client_table['syn_bank_observed_total_zar'] = (
        client_table['txn_banking_total_zar'] + 
        client_table['cross_border_total_zar'] + 
        client_table['trade_finance_total_zar'] + 
        client_table['lending_signal_total_zar']
    )

    return client_table.sort_values('syn_bank_observed_total_zar', ascending=False)

def convert_client_table_to_dashboard_schema(
    client_table: pd.DataFrame,
    *,
    calculation_details: dict | None = None,
    missing_data: dict | None = None,
    score_weights: dict | None = None,
) -> list:
    """
    Transforms the raw aggregated client DataFrame into the exact JSON schema 
    required by the frontend dashboard.
    
    Args:
        client_table: DataFrame containing columns like entity_id, entity_name, sector, 
                      txn_banking_total_zar, cross_border_total_zar, trade_finance_total_zar, 
                      lending_signal_total_zar, and syn_bank_observed_total_zar.
                      
    Returns:
        list of dicts: Clean records matching the dashboard frontend schema.
    """
    formatted_records = []
    calculation_details = calculation_details or {}
    formulas_by_company = calculation_details.get("formulas", {})
    missing_rows = {
        str(row.get("company")): row
        for row in calculation_details.get("missing_rows", [])
    }
    missing_data = missing_data or {}
    score_weights = score_weights or {
        "gap_weight": 0.50,
        "sens_weight": 0.40,
        "relationship_weight": 0.10,
    }
    
    for _, row in client_table.iterrows():
        observed_total = float(row['syn_bank_observed_total_zar'])
        
        if observed_total > 0:
            txn_pct = round((row['txn_banking_total_zar'] / observed_total) * 100, 2)
            cb_pct = round((row['cross_border_total_zar'] / observed_total) * 100, 2)
            tf_pct = round((row['trade_finance_total_zar'] / observed_total) * 100, 2)
            ib_pct = round((row['lending_signal_total_zar'] / observed_total) * 100, 2)
        else:
            txn_pct = cb_pct = tf_pct = ib_pct = 0.0

        # (If you have an external total addressable wallet column, swap it in here)
        estimated_total_wallet = _number_or_none(row.get("total"))
        syn_bank_share = (
            round((observed_total / estimated_total_wallet) * 100, 2)
            if estimated_total_wallet and estimated_total_wallet > 0
            else 0.0
        )
        wallet_gap = (
            max(0.0, estimated_total_wallet - observed_total)
            if estimated_total_wallet is not None
            else None
        )
        company = str(row["entity_name"])
        total_score = _number_or_none(row.get("total_score"))
        company_formula = formulas_by_company.get(company, {})
        confidence = {
            pillar: {
                "level": _json_safe(row.get(f"{pillar}_confidence")),
                "reasons": company_formula.get("pillars", {})
                .get(pillar, {})
                .get("confidence_reasons", []),
            }
            for pillar in (
                "transactional_banking",
                "global_markets",
                "investment_banking",
            )
        }
        pillar_scores = {
            pillar: _score_detail(row, pillar, score_weights)
            for pillar in (
                "transactional_banking",
                "global_markets",
                "investment_banking",
            )
        }
        
        record = {
            "entity_id": str(row['entity_id']),
            "entity_name": str(row['entity_name']),
            "sector": str(row['sector']),

            "syn_txn_banking_pct": txn_pct,
            "syn_global_markets_pct": cb_pct,
            "syn_trade_finance_pct": tf_pct,

            "syn_txn_banking_total_zar": _json_safe(row['txn_banking_total_zar']),
            "syn_global_markets_total_zar": _json_safe(row['cross_border_total_zar']),
            "syn_trade_finance_total_zar": _json_safe(row['trade_finance_total_zar']),
            "syn_lending_ib_total_zar": _json_safe(row['lending_signal_total_zar']),

            "lending_ib_pct": ib_pct,
            "estimated_total_wallet_zar": estimated_total_wallet,
            "syn_bank_share_pct": syn_bank_share,
            "wallet_gap_zar": wallet_gap,

            "company_transactional_banking_total_zar": _json_safe(row['transactional_banking']),
            "company_global_markets_total_zar": _json_safe(row['global_markets']),
            "company_investment_banking_total_zar": _json_safe(row['investment_banking']),
            
            # TODO: figure out these
            "refinancing_flag": False,
            "refinancing_window_days": None,
            "import_mismatch_flag": bool(row['lending_signal_txn_count'] > 5), # Example logical flag based on data
            "opportunity_score": round(total_score * 100, 2) if total_score is not None else 0.0,
            "pillar_scores": pillar_scores,
            "confidence": confidence,
            "wallet_calculation": company_formula,
            "score_calculation": {
                "formula": "wallet-gap-weighted average of the three pillar scores",
                "weights": score_weights,
                "total_score_0_to_1": total_score,
                "pillar_scores": pillar_scores,
            },
            "missing_data": {
                "fields": missing_data.get(company, []),
                "update_template": missing_rows.get(company),
            },
        }

        # Compatibility keys consumed by the current React frontend.
        record.update({
            "txn_banking_pct": txn_pct,
            "cross_border_pct": cb_pct,
            "trade_finance_pct": tf_pct,
            "syn_txt_banking_total_zar": record["syn_txn_banking_total_zar"],
            "syn_trade_finace_total_zar": record["syn_trade_finance_total_zar"],
        })
        
        formatted_records.append(record)
        
    return formatted_records

def _score_detail(row, pillar: str, weights: dict) -> dict:
    prefix = f"{pillar}_"
    return {
        "score": _json_safe(row.get(f"{prefix}score")),
        "formula": (
            "gap_weight * gap_score + sens_weight * sens_score + "
            "relationship_weight * relationship_score"
        ),
        "weights": weights,
        "components": {
            name: _json_safe(row.get(f"{prefix}{name}"))
            for name in (
                "total_wallet",
                "captured_wallet",
                "wallet_gap",
                "gap_score",
                "raw_sens",
                "sens_score",
                "current_wallet_share",
                "relationship_score",
            )
        },
    }


def _number_or_none(value):
    value = _json_safe(value)
    return float(value) if isinstance(value, (int, float)) else None


def _json_safe(value):
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save_dashboard_clients_to_json(
    client_records,
    output_path=None,
):
    """
    Takes the formatted list of client dictionaries and saves them as a pretty-printed 
    JSON file to the specified target path.
    """
    # Resolve the file path relative to the current script's location
    target_file = Path(
        output_path
        or Path(__file__).resolve().parents[2] / "data" / "client_data.json"
    )
    target_file.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace keeps API readers from observing a partially-written file.
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=target_file.parent, delete=False
    ) as output:
        json.dump(client_records, output, indent=2, ensure_ascii=False, allow_nan=False)
        temporary_path = Path(output.name)
    os.replace(temporary_path, target_file)
        
    print(f"Successfully saved {len(client_records)} client records to {target_file.resolve()}")

def reload_client_data(data_dir=None):
    data_dir = Path(data_dir or Path(__file__).resolve().parents[2] / "data")
    cross_border_payments = pd.read_csv(data_dir / "cross_border_payments.csv")
    trade_finance = pd.read_csv(data_dir / "trade_finance.csv")
    transactional_banking = pd.read_csv(data_dir / "transactional_banking.csv")

    company = pd.read_json(data_dir / "json" / "current_external_data.json")
    sens = pd.read_json(data_dir / "json" / "current_sens_data.json")
    
    print("[data-agg] Loaded csv")
    # Currency casing fix (found during EDA: 'ZAR' vs 'zar')
    transactional_banking['currency'] = transactional_banking['currency'].str.upper()
    overlap_df = find_cross_ledger_overlaps(amount_tolerance_pct=2, 
                                            cross_border_df=cross_border_payments, 
                                            transactional_df=transactional_banking, 
                                            day_tolerance=3)
    
    print("[data-agg] Overlap found")
    final_client_table = build_client_wallet_baseline(
        transactional_df=transactional_banking,
        cross_border_df=cross_border_payments,
        trade_finance_df=trade_finance,
        overlap_df=overlap_df
    )
    print("[data-agg] final client table")
    
    try:
        df, details, missing = calculate_total_wallet_size(
            company_df=company,
            corporate_events_df=sens,
            return_calculation_details=True,
            return_missing_data=True,
        )
    except ValueError as error:
        if "currency" not in str(error):
            raise
        df, details, missing = calculate_total_wallet_size(
            company_df=company,
            return_calculation_details=True,
            return_missing_data=True,
        )

    print("[data-agg] total wallet")

    final_client_table = final_client_table.merge(
        df, 
        left_on='entity_name', 
        right_on='company', 
        how='left'
    )
    print("[data-agg] Merged external wallet data")

    for score_column in (
        "transactional_banking_opportunity_score",
        "global_markets_opportunity_score",
        "investment_banking_opportunity_score",
    ):
        if score_column not in sens:
            sens[score_column] = 0.0
        sens[score_column] = pd.to_numeric(sens[score_column], errors="coerce").fillna(0)
    scores = calculate_client_score(final_client_table, sens, df)
    final_client_table = final_client_table.merge(
        scores.drop(columns=["entity_name"], errors="ignore"),
        on="entity_id",
        how="left",
    )
    formatted = convert_client_table_to_dashboard_schema(
        final_client_table,
        calculation_details=details,
        missing_data=missing,
    )
    print("[data-agg] formatted")
    save_dashboard_clients_to_json(formatted, data_dir / "client_data.json")
    print("[data-agg] saved to data folder")

# ==========================================
# Example usage in a backend route/service:
# ==========================================
if __name__ == "__main__":
    import pandas as pd
    pd.options.display.float_format = '{:,.2f}'.format

    reload_client_data()
