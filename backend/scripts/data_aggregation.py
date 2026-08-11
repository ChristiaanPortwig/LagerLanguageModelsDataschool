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

# ==========================================
# Example usage in a backend route/service:
# ==========================================
if __name__ == "__main__":
    # overlap_df = find_cross_ledger_overlaps(...) # from the previous function
    
    # final_client_table = build_client_wallet_baseline(
    #     transactional_df=transactional_banking,
    #     cross_border_df=cross_border_payments,
    #     trade_finance_df=trade_finance,
    #     overlap_df=overlap_df
    # )
    
    # Convert to dictionary/JSON to send to frontend dashboard
    # dashboard_json = final_client_table.to_dict(orient='records')
    pass