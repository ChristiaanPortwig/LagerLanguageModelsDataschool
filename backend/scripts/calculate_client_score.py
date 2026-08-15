"""Calculate client opportunity scores from wallet and SENS data."""

from __future__ import annotations

import math
from numbers import Number

import pandas as pd


PILLARS = (
    "transactional_banking",
    "global_markets",
    "investment_banking",
)

# Trade finance belongs to the transactional-banking pillar in the wallet-size
# and SENS scoring definitions used by data_processing_exploration.ipynb.
CAPTURED_WALLET_COLUMNS = {
    "transactional_banking": (
        "txn_banking_total_zar",
        "trade_finance_total_zar",
    ),
    "global_markets": ("cross_border_total_zar",),
    "investment_banking": ("lending_signal_total_zar",),
}

SENS_SCORE_COLUMNS = {
    pillar: f"{pillar}_opportunity_score" for pillar in PILLARS
}


def calculate_client_score(
    final_client_table: pd.DataFrame,
    decayed_sens: pd.DataFrame,
    wallet_size: pd.DataFrame,
    gap_weight: float = 0.50,
    sens_weight: float = 0.40,
    relationship_weight: float = 0.10,
) -> pd.DataFrame:
    """Return component, pillar, and total scores for every client.

    The three input dataframes follow the schemas used in
    ``notebooks/data_processing_exploration.ipynb``:

    * ``final_client_table`` contains one row per client and the captured-wallet
      columns produced by ``build_client_wallet_baseline``.
    * ``decayed_sens`` contains one or more announcements per company and the
      three decayed ``*_opportunity_score`` columns. Scores are summed by
      company and pillar to produce ``RawSENS``. A company without an
      announcement receives a raw SENS value of zero.
    * ``wallet_size`` contains the three estimated wallet pillars and identifies
      companies either with a ``company`` column or by its index.

    For each company and pillar, the function calculates::

        wallet_gap = total_wallet - captured_wallet
        gap_score = wallet_gap / sum(wallet_gap across companies)
        sens_score = raw_sens / sum(raw_sens across companies)
        relationship_score = percentile_rank(current_wallet_share)
        pillar_score = (gap_weight * gap_score
                        + sens_weight * sens_score
                        + relationship_weight * relationship_score)

    ``pandas.Series.rank(method="average", pct=True)`` supplies the percentile
    rank, including average ranks for ties. ``total_score`` is the wallet-gap-
    weighted average of the available pillar scores for each company. Scores
    are returned on a 0-to-1 scale. The inputs are not modified.

    When every company has a zero gap or zero RawSENS value for a pillar, that
    normalized component is set to zero rather than dividing by zero. A total
    score is undefined (``NaN``) when a client's pillar gaps sum to zero.

    Raises:
        TypeError: If any input is not a pandas DataFrame.
        ValueError: If required columns are absent, company names are duplicated,
            or the weights are invalid or do not sum to one.
    """
    _validate_dataframes(final_client_table, decayed_sens, wallet_size)
    _validate_weights(gap_weight, sens_weight, relationship_weight)

    required_client_columns = {
        "entity_name",
        *(
            column
            for columns in CAPTURED_WALLET_COLUMNS.values()
            for column in columns
        ),
    }
    _require_columns(
        final_client_table, required_client_columns, "final_client_table"
    )
    _require_columns(
        decayed_sens,
        {"company", *SENS_SCORE_COLUMNS.values()},
        "decayed_sens",
    )
    _require_columns(wallet_size, set(PILLARS), "wallet_size")

    clients = final_client_table.copy(deep=True)
    if clients["entity_name"].isna().any():
        raise ValueError("final_client_table contains a missing entity_name")
    if clients["entity_name"].duplicated().any():
        duplicates = _duplicate_names(clients["entity_name"])
        raise ValueError(
            "final_client_table must contain one row per entity_name; duplicates: "
            + ", ".join(duplicates)
        )

    wallets = _wallets_by_company(wallet_size)
    sens = _sens_by_company(decayed_sens)

    identifier_columns = [
        column for column in ("entity_id", "entity_name") if column in clients
    ]
    result = clients[identifier_columns].reset_index(drop=True).copy()
    company_names = clients["entity_name"].reset_index(drop=True)
    wallets = wallets.reindex(company_names).reset_index(drop=True)
    sens = sens.reindex(company_names, fill_value=0.0).reset_index(drop=True)

    gaps: dict[str, pd.Series] = {}
    pillar_scores: dict[str, pd.Series] = {}

    for pillar in PILLARS:
        total_wallet = _numeric_series(
            wallets[pillar], f"wallet_size.{pillar}"
        )
        captured_wallet = sum(
            (
                _numeric_series(
                    clients[column].reset_index(drop=True),
                    f"final_client_table.{column}",
                )
                for column in CAPTURED_WALLET_COLUMNS[pillar]
            ),
            start=pd.Series(0.0, index=result.index),
        )
        wallet_gap = total_wallet - captured_wallet
        raw_sens = _numeric_series(
            sens[SENS_SCORE_COLUMNS[pillar]],
            f"decayed_sens.{SENS_SCORE_COLUMNS[pillar]}",
        )
        current_wallet_share = captured_wallet.div(
            total_wallet.where(total_wallet != 0)
        )

        gap_score = _normalize(wallet_gap)
        sens_score = _normalize(raw_sens)
        relationship_score = current_wallet_share.rank(
            method="average", pct=True
        )
        pillar_score = (
            gap_weight * gap_score
            + sens_weight * sens_score
            + relationship_weight * relationship_score
        )

        prefix = f"{pillar}_"
        result[f"{prefix}total_wallet"] = total_wallet
        result[f"{prefix}captured_wallet"] = captured_wallet
        result[f"{prefix}wallet_gap"] = wallet_gap
        result[f"{prefix}gap_score"] = gap_score
        result[f"{prefix}raw_sens"] = raw_sens
        result[f"{prefix}sens_score"] = sens_score
        result[f"{prefix}current_wallet_share"] = current_wallet_share
        result[f"{prefix}relationship_score"] = relationship_score
        result[f"{prefix}score"] = pillar_score

        gaps[pillar] = wallet_gap
        pillar_scores[pillar] = pillar_score

    gap_frame = pd.DataFrame(gaps)
    score_frame = pd.DataFrame(pillar_scores)
    scored_gaps = gap_frame.where(score_frame.notna())
    total_gap = scored_gaps.sum(axis=1, min_count=1)
    weighted_score = (gap_frame * score_frame).sum(axis=1, min_count=1)
    result["total_score"] = weighted_score.div(total_gap.where(total_gap != 0))

    return result


def calculate_client_scores(
    final_client_table: pd.DataFrame,
    decayed_sens: pd.DataFrame,
    wallet_size: pd.DataFrame,
    gap_weight: float = 0.50,
    sens_weight: float = 0.40,
    relationship_weight: float = 0.10,
) -> pd.DataFrame:
    """Plural-name compatibility wrapper for :func:`calculate_client_score`."""
    return calculate_client_score(
        final_client_table,
        decayed_sens,
        wallet_size,
        gap_weight,
        sens_weight,
        relationship_weight,
    )


def _validate_dataframes(*dataframes: pd.DataFrame) -> None:
    names = ("final_client_table", "decayed_sens", "wallet_size")
    for name, dataframe in zip(names, dataframes):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError(f"{name} must be a pandas DataFrame")


def _validate_weights(*weights: float) -> None:
    names = ("gap_weight", "sens_weight", "relationship_weight")
    for name, weight in zip(names, weights):
        if (
            isinstance(weight, bool)
            or not isinstance(weight, Number)
            or not math.isfinite(float(weight))
            or weight < 0
        ):
            raise ValueError(f"{name} must be a finite non-negative number")
    if not math.isclose(sum(float(weight) for weight in weights), 1.0):
        raise ValueError("score weights must sum to 1")


def _require_columns(
    dataframe: pd.DataFrame, required: set[str], dataframe_name: str
) -> None:
    missing = sorted(required.difference(dataframe.columns))
    if missing:
        raise ValueError(
            f"{dataframe_name} is missing required columns: {', '.join(missing)}"
        )


def _wallets_by_company(wallet_size: pd.DataFrame) -> pd.DataFrame:
    wallets = wallet_size.copy(deep=True)
    if "company" in wallets.columns:
        company_names = wallets["company"]
        wallets = wallets.drop(columns="company")
    else:
        company_names = pd.Series(wallets.index, index=wallets.index)

    if company_names.isna().any():
        raise ValueError("wallet_size contains a missing company name")
    if company_names.duplicated().any():
        duplicates = _duplicate_names(company_names)
        raise ValueError(
            "wallet_size must contain one row per company; duplicates: "
            + ", ".join(duplicates)
        )

    wallets.index = pd.Index(company_names, name="company")
    return wallets.loc[:, list(PILLARS)]


def _sens_by_company(decayed_sens: pd.DataFrame) -> pd.DataFrame:
    sens = decayed_sens.loc[
        :, ["company", *SENS_SCORE_COLUMNS.values()]
    ].copy(deep=True)
    for column in SENS_SCORE_COLUMNS.values():
        sens[column] = _numeric_series(sens[column], f"decayed_sens.{column}")
    return sens.groupby("company", sort=False)[
        list(SENS_SCORE_COLUMNS.values())
    ].sum(min_count=1)


def _numeric_series(series: pd.Series, name: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    invalid = series.notna() & numeric.isna()
    if invalid.any():
        raise ValueError(f"{name} contains non-numeric values")
    return numeric.astype(float)


def _normalize(values: pd.Series) -> pd.Series:
    denominator = values.sum(min_count=1)
    if pd.isna(denominator):
        return pd.Series(math.nan, index=values.index, dtype=float)
    if math.isclose(float(denominator), 0.0, abs_tol=1e-12):
        return values.where(values.isna(), 0.0).astype(float)
    return values / denominator


def _duplicate_names(names: pd.Series) -> list[str]:
    return sorted(str(name) for name in names[names.duplicated(keep=False)].unique())


__all__ = [
    "CAPTURED_WALLET_COLUMNS",
    "PILLARS",
    "SENS_SCORE_COLUMNS",
    "calculate_client_score",
    "calculate_client_scores",
]
