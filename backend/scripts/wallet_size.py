"""Estimate each company's banking wallet from disclosed financial data."""

from __future__ import annotations

import math
import logging
import re
from collections import defaultdict
from typing import NamedTuple

import pandas as pd


LOGGER = logging.getLogger(__name__)


_PILLARS = {
    "transactional_banking": (
        "payments",
        "collections",
        "liquidity_management",
        "trade_finance",
        "guarantees",
    ),
    "global_markets": ("foreign_exchange", "interest_rates", "commodities"),
    "investment_banking": (
        "lending",
        "debt_capital_markets",
        "equity_capital_markets",
        "advisory",
        "project_finance",
    ),
}

_CONFIDENCE = {"A": "high", "B": "medium", "C": "low"}


# Fields that would support a better-than-low estimate for each product. These
# are used only for diagnostics; the estimator functions remain the source of
# truth for the selected value and tier.
_PREFERRED_INPUTS = {
    "payments": (
        "cost_of_sales",
        "employee_expenses",
        "tax_paid",
        "dividends_paid",
    ),
    "collections": ("collections_value", "adjusted_collections_value"),
    "liquidity_management": (
        "average_cash_and_cash_equivalents",
        "average_cash_balance",
        "cash_and_cash_equivalents",
    ),
    "trade_finance": (
        "trade_exposure_value",
        "letters_of_credit_disclosed",
        "imports_value",
        "exports_value",
        "trade_exposure_share",
    ),
    "guarantees": (
        "guarantees_outstanding",
        "guarantee_project_obligations",
        "contingent_liabilities",
    ),
    "foreign_exchange": (
        "fx_transaction_value",
        "fx_derivative_notional",
        "fx_exposure_value",
        "foreign_revenue",
        "imports_value",
        "foreign_revenue_share",
    ),
    "interest_rates": (
        "interest_rate_derivative_notional",
        "floating_rate_debt",
    ),
    "commodities": (
        "commodity_derivative_notional",
        "commodity_exposure_value",
    ),
    "lending": (
        "bank_loans_and_credit_facilities",
        "bank_loan_debt",
        "explicit_bank_loans",
        "non_bank_debt",
        "identified_bonds",
        "bond_debt",
    ),
    "debt_capital_markets": (
        "_event_dcm_value",
        "bond_issue_value",
        "upcoming_bond_maturities_value",
    ),
    "equity_capital_markets": (
        "_event_ecm_value",
        "equity_raise_value",
        "rights_issue_value",
        "equity_issuance_value",
        "other_equity_issuance_value",
    ),
    "advisory": (
        "_event_advisory_value",
        "deal_value",
        "acquisition_value",
        "disposal_value",
        "restructuring_value",
        "corporate_transaction_value",
    ),
    "project_finance": (
        "_event_project_financing",
        "external_project_financing",
        "external_debt_raised",
        "project_debt",
        "project_facility_value",
    ),
}


def calculate_total_wallet_size(
    company_df: pd.DataFrame,
    corporate_events_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return wallet estimates and pillar confidence, indexed by company.

    ``company_df`` is intended to be the standardized company-level dataframe
    produced in ``data_processing_exploration``. Monetary values must already
    share a unit within each row; when ``reporting_unit`` is present it must be
    ``"units"``. If several rows exist for a company, the latest report is used.

    ``corporate_events_df`` is optional. It may be a date-filtered SENS-like
    dataframe with ``company``, ``event_type``, and ``event_value`` columns.
    Passing it can supply direct DCM, ECM, advisory, and project-finance values;
    the company-level dataframe remains the primary source.

    Unavailable products are omitted from their pillar subtotal. A pillar is
    null with confidence ``"can't estimate"`` only when none of its products
    has a defensible Tier A, B, or C estimate. ``total`` is null unless all
    three pillars can be estimated.
    """
    rows = _prepare_company_rows(company_df)
    if corporate_events_df is not None:
        rows = _add_event_values(rows, corporate_events_df)

    records = []
    for _, row in rows.iterrows():
        estimates = {
            product: _PRODUCT_ESTIMATORS[product](row)
            for products in _PILLARS.values()
            for product in products
        }
        record = {"company": row["company"]}
        for pillar, products in _PILLARS.items():
            selected = [estimates[product] for product in products]
            record[pillar] = _pillar_total(selected)
            record[f"{pillar}_confidence"] = _pillar_confidence(selected)
            _log_low_confidence(
                row["company"],
                pillar,
                products,
                estimates,
                row,
            )

        pillar_values = [record[pillar] for pillar in _PILLARS]
        record["total"] = (
            sum(pillar_values)
            if all(pd.notna(value) for value in pillar_values)
            else math.nan
        )
        records.append(record)

    columns = [
        "transactional_banking",
        "global_markets",
        "investment_banking",
        "total",
        "transactional_banking_confidence",
        "global_markets_confidence",
        "investment_banking_confidence",
    ]
    if not records:
        return pd.DataFrame(columns=columns, index=pd.Index([], name="company"))
    return pd.DataFrame.from_records(records).set_index("company")[columns]


class _Estimate(NamedTuple):
    value: float | None
    tier: str | None


def _prepare_company_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("company_df must be a pandas DataFrame")
    if "company" not in dataframe.columns:
        raise ValueError("company_df is missing required column: company")

    rows = dataframe.copy(deep=True)
    rows = rows.loc[rows["company"].map(_has_value)].copy()
    if "reporting_unit" in rows:
        units = (
            rows.loc[rows["reporting_unit"].map(_has_value), "reporting_unit"]
            .astype(str)
            .str.casefold()
        )
        if not units.isin(["units"]).all():
            raise ValueError(
                "company_df monetary values must be standardized to base 'units'"
            )

    rows["_input_order"] = range(len(rows))
    rows["_company_key"] = rows["company"].astype(str).str.strip().str.casefold()
    rows["_report_date"] = (
        pd.to_datetime(rows.get("report_date"), errors="coerce")
        if "report_date" in rows
        else pd.NaT
    )
    rows = rows.sort_values("_report_date", na_position="first")
    rows = rows.drop_duplicates("_company_key", keep="last")
    return rows.sort_values("_input_order").reset_index(drop=True)


def _add_event_values(company_rows: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    required = {"company", "event_type", "event_value"}
    if not isinstance(events, pd.DataFrame):
        raise TypeError("corporate_events_df must be a pandas DataFrame")
    missing = required - set(events.columns)
    if missing:
        raise ValueError(
            "corporate_events_df is missing required columns: "
            + ", ".join(sorted(missing))
        )
    if "event_unit" in events:
        units = (
            events.loc[events["event_unit"].map(_has_value), "event_unit"]
            .astype(str)
            .str.casefold()
        )
        if not units.isin(["units"]).all():
            raise ValueError(
                "corporate event values must be standardized to base 'units'"
            )

    company_currencies = {}
    if "reporting_currency" in company_rows:
        company_currencies = dict(
            zip(
                company_rows["_company_key"],
                company_rows["reporting_currency"].map(
                    lambda value: str(value).strip().upper()
                    if _has_value(value)
                    else None
                ),
            )
        )

    totals: defaultdict[tuple[str, str], float] = defaultdict(float)
    for _, event in events.iterrows():
        company = event.get("company")
        value = _number(event.get("event_value"))
        category = _event_category(event.get("event_type"))
        if not (_has_value(company) and value is not None and category is not None):
            continue
        company_key = str(company).strip().casefold()
        event_currency = event.get("currency")
        expected_currency = company_currencies.get(company_key)
        if (
            _has_value(event_currency)
            and _has_value(expected_currency)
            and str(event_currency).strip().upper() != expected_currency
        ):
            raise ValueError(
                f"corporate event currency for {company!r} does not match "
                "company_df reporting_currency"
            )
        totals[(company_key, category)] += value

    result = company_rows.copy()
    for category in set(category for _, category in totals):
        result[category] = result["_company_key"].map(
            lambda key: totals.get((key, category), math.nan)
        )
    return result


def _payments(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _sum_required(
                row, "cost_of_sales", "employee_expenses", "tax_paid", "dividends_paid"
            ),
        ),
        ("B", _sum_required(row, "cost_of_sales", "employee_expenses")),
        ("C", _value(row, "revenue")),
    )


def _collections(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _value(row, "collections_value", "revenue")),
        ("B", _value(row, "adjusted_collections_value")),
        ("C", _value(row, "revenue")),
    )


def _liquidity_management(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _value(row, "average_cash_and_cash_equivalents", "average_cash_balance")),
        ("B", _value(row, "cash_and_cash_equivalents")),
        ("C", _value(row, "current_cash_balance")),
    )


def _trade_finance(row: pd.Series) -> _Estimate:
    explicit_trade = _value(row, "trade_exposure_value", "letters_of_credit_disclosed")
    if explicit_trade is None:
        explicit_trade = _sum_required(row, "imports_value", "exports_value")
    cost_of_sales = _value(row, "cost_of_sales")
    trade_share = _share(row, "trade_exposure_share")
    return _choose(
        ("A", explicit_trade),
        ("B", _multiply(cost_of_sales, trade_share)),
        ("C", cost_of_sales),
    )


def _guarantees(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _value(row, "guarantees_outstanding")),
        ("B", _value(row, "guarantee_project_obligations", "contingent_liabilities")),
    )


def _foreign_exchange(row: pd.Series) -> _Estimate:
    foreign_revenue = _value(row, "foreign_revenue")
    imports = _value(row, "imports_value")
    proxy = foreign_revenue
    if proxy is None:
        proxy = _multiply(_value(row, "revenue"), _share(row, "foreign_revenue_share"))
    return _choose(
        (
            "A",
            _value(
                row,
                "fx_transaction_value",
                "fx_derivative_notional",
                "fx_exposure_value",
            ),
        ),
        ("B", _add(foreign_revenue, imports)),
        ("C", proxy),
    )


def _interest_rates(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _value(row, "interest_rate_derivative_notional")),
        ("B", _value(row, "floating_rate_debt")),
        ("C", _value(row, "total_debt")),
    )


def _commodities(row: pd.Series) -> _Estimate:
    proxy = _multiply(_value(row, "revenue"), _share(row, "commodity_exposure_share"))
    if proxy is None:
        proxy = _value(row, "commodity_linked_revenue")
    return _choose(
        ("A", _value(row, "commodity_derivative_notional")),
        ("B", _value(row, "commodity_exposure_value")),
        ("C", proxy),
    )


def _lending(row: pd.Series) -> _Estimate:
    direct = _value(
        row,
        "bank_loans_and_credit_facilities",
        "bank_loan_debt",
        "explicit_bank_loans",
    )
    debt = _value(row, "total_debt")
    deduction = _value(row, "non_bank_debt", "identified_bonds", "bond_debt")
    derived = (
        max(0.0, debt - deduction)
        if debt is not None and deduction is not None
        else None
    )
    return _choose(("A", direct), ("B", derived), ("C", debt))


def _debt_capital_markets(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _value(row, "_event_dcm_value", "bond_issue_value")),
        ("B", _value(row, "upcoming_bond_maturities_value")),
    )


def _equity_capital_markets(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _value(row, "_event_ecm_value", "equity_raise_value", "rights_issue_value"),
        ),
        ("B", _value(row, "equity_issuance_value", "other_equity_issuance_value")),
    )


def _advisory(row: pd.Series) -> _Estimate:
    direct = _value(row, "_event_advisory_value", "deal_value")
    if direct is None:
        direct_values = _values(
            row, "acquisition_value", "disposal_value", "restructuring_value"
        )
        direct = sum(direct_values) if direct_values else None
    return _choose(
        ("A", direct),
        ("B", _value(row, "corporate_transaction_value")),
    )


def _project_finance(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _value(
                row,
                "_event_project_financing",
                "external_project_financing",
                "external_debt_raised",
            ),
        ),
        ("B", _value(row, "project_debt", "project_facility_value")),
        (
            "C",
            _value(
                row,
                "_event_project_value",
                "project_or_contract_value",
                "project_value",
                "capital_expenditure",
            ),
        ),
    )


_PRODUCT_ESTIMATORS = {
    "payments": _payments,
    "collections": _collections,
    "liquidity_management": _liquidity_management,
    "trade_finance": _trade_finance,
    "guarantees": _guarantees,
    "foreign_exchange": _foreign_exchange,
    "interest_rates": _interest_rates,
    "commodities": _commodities,
    "lending": _lending,
    "debt_capital_markets": _debt_capital_markets,
    "equity_capital_markets": _equity_capital_markets,
    "advisory": _advisory,
    "project_finance": _project_finance,
}


def _choose(*tiers: tuple[str, float | None]) -> _Estimate:
    for tier, value in tiers:
        if value is not None:
            return _Estimate(value, tier)
    return _Estimate(None, None)


def _pillar_total(estimates: list[_Estimate]) -> float:
    values = [estimate.value for estimate in estimates if estimate.value is not None]
    return sum(values) if values else math.nan


def _pillar_confidence(estimates: list[_Estimate]) -> str:
    tiers = [estimate.tier for estimate in estimates if estimate.tier is not None]
    if not tiers:
        return "can't estimate"
    return _CONFIDENCE[max(tiers)]


def _log_low_confidence(
    company,
    pillar: str,
    products: tuple[str, ...],
    estimates: dict[str, _Estimate],
    row: pd.Series,
) -> None:
    confidence = _pillar_confidence([estimates[product] for product in products])
    if confidence not in {"low", "can't estimate"}:
        return

    reasons = []
    for product in products:
        estimate = estimates[product]
        if confidence == "low" and estimate.tier not in {"C", None}:
            continue

        status = "unavailable" if estimate.tier is None else "Tier C proxy"
        missing = [
            field
            for field in _PREFERRED_INPUTS.get(product, ())
            if _value(row, field) is None
        ]
        detail = f"{product}: {status}"
        if missing:
            detail += "; missing " + ", ".join(missing)
        reasons.append(detail)

    LOGGER.warning(
        "%s: %s confidence is %s because %s",
        company,
        pillar,
        confidence,
        " | ".join(reasons),
    )


def _event_category(event_type) -> str | None:
    if not _has_value(event_type):
        return None
    value = re.sub(r"[^a-z]+", " ", str(event_type).casefold()).strip()
    if any(term in value for term in ("bond issue", "note issue", "debt issuance")):
        return "_event_dcm_value"
    if any(term in value for term in ("rights issue", "equity raise", "share issue")):
        return "_event_ecm_value"
    if any(
        term in value for term in ("acquisition", "disposal", "merger", "restructuring")
    ):
        return "_event_advisory_value"
    if "project" in value and any(
        term in value for term in ("financ", "debt", "facility")
    ):
        return "_event_project_financing"
    if "project" in value:
        return "_event_project_value"
    return None


def _sum_required(row: pd.Series, *names: str) -> float | None:
    values = [_value(row, name) for name in names]
    return sum(values) if all(value is not None for value in values) else None


def _values(row: pd.Series, *names: str) -> list[float]:
    return [value for name in names if (value := _value(row, name)) is not None]


def _value(row: pd.Series, *names: str) -> float | None:
    for name in names:
        if name in row.index and (value := _number(row[name])) is not None:
            return value
    return None


def _share(row: pd.Series, name: str) -> float | None:
    value = _value(row, name)
    return value if value is not None and value <= 1 else None


def _add(left: float | None, right: float | None) -> float | None:
    return left + right if left is not None and right is not None else None


def _multiply(left: float | None, right: float | None) -> float | None:
    return left * right if left is not None and right is not None else None


def _number(value) -> float | None:
    if not _has_value(value) or isinstance(value, bool):
        return None
    supplied = str(value).strip().replace(",", "")
    negative = supplied.startswith("(") and supplied.endswith(")")
    supplied = supplied.strip("()")
    try:
        number = float(supplied)
    except (TypeError, ValueError):
        return None
    if negative:
        number = -number
    return number if math.isfinite(number) and number >= 0 else None


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return True
    try:
        return not bool(missing)
    except ValueError:
        return True
