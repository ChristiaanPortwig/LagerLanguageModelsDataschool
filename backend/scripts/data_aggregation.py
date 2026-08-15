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

import pandas as pd
import json
from pathlib import Path

from scripts.wallet_size import calculate_total_wallet_size


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

def convert_client_table_to_dashboard_schema(client_table: pd.DataFrame) -> list:
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

    print("COLOUMSN:=========================\n\n\n",client_table.columns)
    
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
        estimated_total_wallet = row['total']
        syn_bank_share = round((observed_total / estimated_total_wallet) * 100, 2) if estimated_total_wallet > 0 else 0.0
        wallet_gap = max(0.0, estimated_total_wallet - observed_total)
        
        record = {
            "entity_id": str(row['entity_id']),
            "entity_name": str(row['entity_name']),
            "sector": str(row['sector']),

            "syn_txn_banking_pct": txn_pct,
            "syn_global_markets_pct": cb_pct,
            "syn_trade_finance_pct": tf_pct,

            "syn_txt_banking_total_zar": row['txn_banking_total_zar'],
            "syn_global_markets_total_zar":row['cross_border_total_zar'],
            "syn_trade_finace_total_zar":row['trade_finance_total_zar'],

            "lending_ib_pct": ib_pct,
            "estimated_total_wallet_zar": float(estimated_total_wallet),
            "syn_bank_share_pct": syn_bank_share,
            "wallet_gap_zar": float(wallet_gap),

            "company_transactional_banking_total_zar": float(row['transactional_banking']),
            "company_global_markets_total_zar":float(row['global_markets']),
            "company_investment_banking_total_zar":float(row['investment_banking']),
            
            # TODO: figure out these
            "refinancing_flag": False,
            "refinancing_window_days": None,
            "import_mismatch_flag": bool(row['lending_signal_txn_count'] > 5), # Example logical flag based on data
            "opportunity_score": round((wallet_gap / 1_000_000_000) * 1.5, 2) # Scaled mock opportunity score
        }
        
        formatted_records.append(record)
        
    return formatted_records

def save_dashboard_clients_to_json(client_records, output_path="../../data/client_data.json"):
    """
    Takes the formatted list of client dictionaries and saves them as a pretty-printed 
    JSON file to the specified target path.
    """
    # Resolve the file path relative to the current script's location
    target_file = Path(__file__).resolve().parent / output_path

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(client_records, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully saved {len(client_records)} client records to {target_file.resolve()}")

def reload_client_data():
    cross_border_payments = pd.read_csv("../data/cross_border_payments.csv")
    trade_finance = pd.read_csv("../data/trade_finance.csv")
    transactional_banking = pd.read_csv("../data/transactional_banking.csv")

    company = pd.read_csv("../data/company_lvl_scraped_new.csv")
    sens = pd.read_csv("../data/sens_scraped_new.csv")
    
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
    
    df = calculate_total_wallet_size(company_df=company, corporate_events_df=sens)

    print("[data-agg] total wallet")

    final_client_table = final_client_table.merge(
        df, 
        left_on='entity_name', 
        right_on='company', 
        how='left'
    )
    print("[data-agg] Merged external wallet data")

    formatted = convert_client_table_to_dashboard_schema(final_client_table)
    print("[data-agg] formatted")
    save_dashboard_clients_to_json(formatted)
    print("[data-agg] saved to data folder")

# ==========================================
# Example usage in a backend route/service:
# ==========================================
if __name__ == "__main__":
    import pandas as pd
    pd.options.display.float_format = '{:,.2f}'.format

    reload_client_data()
