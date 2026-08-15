"""Estimate each company's banking wallet from disclosed financial data."""

from __future__ import annotations

import math
import logging
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, NamedTuple

import pandas as pd

from scripts.data_processing import Data_Processor


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
    *,
    return_missing_data: bool = False,
    return_calculation_details: bool = False,
):
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
    three pillars can be estimated. Set ``return_missing_data`` to receive a
    second return value mapping each company to missing source-data keywords.

    Set ``return_calculation_details`` to receive a JSON-serializable object as
    the second return value. Its ``formulas`` member records the selected tier,
    formula, inputs, and value for every product, pillar, and company total.
    Its ``missing_rows`` member contains company-row templates whose null fields
    can be populated and merged back into ``company_df`` to improve low or
    unavailable estimates. When both return flags are true, the missing keyword
    mapping is returned as a third value.
    """
    my_processor = Data_Processor()
    standard_ext_data, standard_sens_data = my_processor.standardize_data(company_df, corporate_events_df)
    new_company_lvl_df, new_sens_df = my_processor.validate_external_data(standard_ext_data, standard_sens_data)

    company_df = new_company_lvl_df
    corporate_events_df = new_sens_df

    rows = _prepare_company_rows(company_df)
    if corporate_events_df is not None:
        rows = _add_event_values(rows, corporate_events_df)

    records = []
    formulas_by_company: dict[str, dict[str, Any]] = {}
    missing_by_company: dict[str, set[str]] = {}
    improvable_by_company: dict[str, set[str]] = {}
    for _, row in rows.iterrows():
        estimates = {
            product: _PRODUCT_ESTIMATORS[product](row)
            for products in _PILLARS.values()
            for product in products
        }
        company = str(row["company"])
        record = {"company": row["company"]}
        company_formulas: dict[str, Any] = {"products": {}, "pillars": {}}
        for product, estimate in estimates.items():
            if estimate.tier != "A":
                improvable_by_company.setdefault(company, set()).update(
                    field
                    for field in _PREFERRED_INPUTS.get(product, ())
                    if _value(row, field) is None
                )
            company_formulas["products"][product] = {
                "tier": estimate.tier,
                "formula": estimate.formula,
                "inputs": estimate.inputs,
                "value": estimate.value,
            }
        for pillar, products in _PILLARS.items():
            selected = [estimates[product] for product in products]
            record[pillar] = _pillar_total(selected)
            record[f"{pillar}_confidence"] = _pillar_confidence(selected)
            included_products = [
                product
                for product in products
                if estimates[product].value is not None
            ]
            company_formulas["pillars"][pillar] = {
                "formula": " + ".join(included_products) or None,
                "included_products": included_products,
                "value": _json_safe(record[pillar]),
                "confidence": record[f"{pillar}_confidence"],
            }
            missing_keywords = _log_low_confidence(
                row["company"],
                pillar,
                products,
                estimates,
                row,
            )
            if missing_keywords:
                missing_by_company.setdefault(
                    str(row["company"]), set()
                ).update(missing_keywords)

        pillar_values = [record[pillar] for pillar in _PILLARS]
        record["total"] = (
            sum(pillar_values)
            if all(pd.notna(value) for value in pillar_values)
            else math.nan
        )
        company_formulas["total"] = {
            "formula": " + ".join(_PILLARS),
            "included_pillars": [
                pillar for pillar in _PILLARS if pd.notna(record[pillar])
            ],
            "value": _json_safe(record["total"]),
        }
        formulas_by_company[company] = company_formulas
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
    missing_data = {
        company: sorted(keywords)
        for company, keywords in missing_by_company.items()
    }
    if not records:
        result = pd.DataFrame(
            columns=columns, index=pd.Index([], name="company")
        )
    else:
        result = pd.DataFrame.from_records(records).set_index("company")[columns]
    calculation_details = {
        "formulas": formulas_by_company,
        "missing_rows": _missing_row_templates(
            rows,
            company_df.columns,
            {
                company: sorted(fields)
                for company, fields in improvable_by_company.items()
            },
        ),
    }
    result.attrs["missing_data_keywords"] = missing_data
    result.attrs["calculation_details"] = calculation_details
    if return_calculation_details and return_missing_data:
        return result, calculation_details, missing_data
    if return_calculation_details:
        return result, calculation_details
    if return_missing_data:
        return result, missing_data
    return result


def missing_wallet_data_keywords(
    company_df: pd.DataFrame,
    corporate_events_df: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Return missing source-data keywords grouped by company.

    Keywords are the preferred disclosed fields that prevented a pillar from
    receiving better than low confidence. This is the dictionary form callers
    can feed back into document research or scraping.
    """
    _, missing_data = calculate_total_wallet_size(
        company_df,
        corporate_events_df,
        return_missing_data=True,
    )
    return missing_data


class _Estimate(NamedTuple):
    value: float | None
    tier: str | None
    formula: str | None
    inputs: dict[str, float]


class _Calculation(NamedTuple):
    value: float | None
    formula: str | None
    inputs: dict[str, float]


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
            _sum_calculation(
                row, "cost_of_sales", "employee_expenses", "tax_paid", "dividends_paid"
            ),
        ),
        ("B", _sum_calculation(row, "cost_of_sales", "employee_expenses")),
        ("C", _direct_calculation(row, "revenue")),
    )


def _collections(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _direct_calculation(row, "collections_value", "revenue")),
        ("B", _direct_calculation(row, "adjusted_collections_value")),
        ("C", _direct_calculation(row, "revenue")),
    )


def _liquidity_management(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _direct_calculation(
                row, "average_cash_and_cash_equivalents", "average_cash_balance"
            ),
        ),
        ("B", _direct_calculation(row, "cash_and_cash_equivalents")),
        ("C", _direct_calculation(row, "current_cash_balance")),
    )


def _trade_finance(row: pd.Series) -> _Estimate:
    explicit_trade = _direct_calculation(
        row, "trade_exposure_value", "letters_of_credit_disclosed"
    )
    if explicit_trade.value is None:
        explicit_trade = _sum_calculation(row, "imports_value", "exports_value")
    return _choose(
        ("A", explicit_trade),
        (
            "B",
            _multiply_calculation(row, "cost_of_sales", "trade_exposure_share"),
        ),
        ("C", _direct_calculation(row, "cost_of_sales")),
    )


def _guarantees(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _direct_calculation(row, "guarantees_outstanding")),
        (
            "B",
            _direct_calculation(
                row, "guarantee_project_obligations", "contingent_liabilities"
            ),
        ),
    )


def _foreign_exchange(row: pd.Series) -> _Estimate:
    proxy = _direct_calculation(row, "foreign_revenue")
    if proxy.value is None:
        proxy = _multiply_calculation(row, "revenue", "foreign_revenue_share")
    return _choose(
        (
            "A",
            _direct_calculation(
                row,
                "fx_transaction_value",
                "fx_derivative_notional",
                "fx_exposure_value",
            ),
        ),
        ("B", _add_calculation(row, "foreign_revenue", "imports_value")),
        ("C", proxy),
    )


def _interest_rates(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _direct_calculation(row, "interest_rate_derivative_notional")),
        ("B", _direct_calculation(row, "floating_rate_debt")),
        ("C", _direct_calculation(row, "total_debt")),
    )


def _commodities(row: pd.Series) -> _Estimate:
    proxy = _multiply_calculation(row, "revenue", "commodity_exposure_share")
    if proxy.value is None:
        proxy = _direct_calculation(row, "commodity_linked_revenue")
    return _choose(
        ("A", _direct_calculation(row, "commodity_derivative_notional")),
        ("B", _direct_calculation(row, "commodity_exposure_value")),
        ("C", proxy),
    )


def _lending(row: pd.Series) -> _Estimate:
    direct = _direct_calculation(
        row,
        "bank_loans_and_credit_facilities",
        "bank_loan_debt",
        "explicit_bank_loans",
    )
    debt = _direct_calculation(row, "total_debt")
    deduction = _direct_calculation(
        row, "non_bank_debt", "identified_bonds", "bond_debt"
    )
    if debt.value is not None and deduction.value is not None:
        derived = _Calculation(
            max(0.0, debt.value - deduction.value),
            f"max(0, total_debt - {deduction.formula})",
            {**debt.inputs, **deduction.inputs},
        )
    else:
        derived = _Calculation(None, None, {})
    return _choose(("A", direct), ("B", derived), ("C", debt))


def _debt_capital_markets(row: pd.Series) -> _Estimate:
    return _choose(
        ("A", _direct_calculation(row, "_event_dcm_value", "bond_issue_value")),
        ("B", _direct_calculation(row, "upcoming_bond_maturities_value")),
    )


def _equity_capital_markets(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _direct_calculation(
                row, "_event_ecm_value", "equity_raise_value", "rights_issue_value"
            ),
        ),
        (
            "B",
            _direct_calculation(
                row, "equity_issuance_value", "other_equity_issuance_value"
            ),
        ),
    )


def _advisory(row: pd.Series) -> _Estimate:
    direct = _direct_calculation(row, "_event_advisory_value", "deal_value")
    if direct.value is None:
        direct = _sum_available_calculation(
            row, "acquisition_value", "disposal_value", "restructuring_value"
        )
    return _choose(
        ("A", direct),
        ("B", _direct_calculation(row, "corporate_transaction_value")),
    )


def _project_finance(row: pd.Series) -> _Estimate:
    return _choose(
        (
            "A",
            _direct_calculation(
                row,
                "_event_project_financing",
                "external_project_financing",
                "external_debt_raised",
            ),
        ),
        ("B", _direct_calculation(row, "project_debt", "project_facility_value")),
        (
            "C",
            _direct_calculation(
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


def _choose(*tiers: tuple[str, _Calculation]) -> _Estimate:
    for tier, calculation in tiers:
        if calculation.value is not None:
            return _Estimate(
                calculation.value,
                tier,
                calculation.formula,
                calculation.inputs,
            )
    return _Estimate(None, None, None, {})


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
) -> list[str]:
    confidence = _pillar_confidence([estimates[product] for product in products])
    if confidence not in {"low", "can't estimate"}:
        return []

    reasons = []
    missing_keywords = set()
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
            missing_keywords.update(missing)
        reasons.append(detail)

    LOGGER.warning(
        "%s: %s confidence is %s because %s",
        company,
        pillar,
        confidence,
        " | ".join(reasons),
    )
    return sorted(missing_keywords)


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


def _direct_calculation(row: pd.Series, *names: str) -> _Calculation:
    for name in names:
        value = _value(row, name)
        if value is not None:
            return _Calculation(value, name, {name: value})
    return _Calculation(None, None, {})


def _sum_calculation(row: pd.Series, *names: str) -> _Calculation:
    inputs = {name: _value(row, name) for name in names}
    if any(value is None for value in inputs.values()):
        return _Calculation(None, None, {})
    resolved = {name: value for name, value in inputs.items() if value is not None}
    return _Calculation(sum(resolved.values()), " + ".join(names), resolved)


def _sum_available_calculation(row: pd.Series, *names: str) -> _Calculation:
    inputs = {
        name: value
        for name in names
        if (value := _value(row, name)) is not None
    }
    if not inputs:
        return _Calculation(None, None, {})
    return _Calculation(sum(inputs.values()), " + ".join(inputs), inputs)


def _add_calculation(
    row: pd.Series, left_name: str, right_name: str
) -> _Calculation:
    return _sum_calculation(row, left_name, right_name)


def _multiply_calculation(
    row: pd.Series, value_name: str, share_name: str
) -> _Calculation:
    value = _value(row, value_name)
    share = _share(row, share_name)
    if value is None or share is None:
        return _Calculation(None, None, {})
    return _Calculation(
        value * share,
        f"{value_name} * {share_name}",
        {value_name: value, share_name: share},
    )


def _missing_row_templates(
    rows: pd.DataFrame,
    original_columns,
    missing_fields_by_company: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Return JSON-safe replacement rows with improvable fields left null."""
    templates = []
    original_columns = list(original_columns)
    for _, row in rows.iterrows():
        company = str(row["company"])
        missing_fields = [
            field
            for field in missing_fields_by_company.get(company, [])
            if not field.startswith("_event_")
        ]
        if not missing_fields:
            continue
        template = {
            column: _json_safe(row.get(column)) for column in original_columns
        }
        for field in missing_fields:
            template[field] = None
        templates.append(template)
    return templates


def _json_safe(value):
    """Convert scalar dataframe values to strict JSON-compatible values."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _value(row: pd.Series, *names: str) -> float | None:
    for name in names:
        if name in row.index and (value := _number(row[name])) is not None:
            return value
    return None


def _share(row: pd.Series, name: str) -> float | None:
    value = _value(row, name)
    return value if value is not None and value <= 1 else None


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

if __name__ == '__main__':
    company = pd.read_csv("../../data/company_lvl_scraped_new.csv")
    sens = pd.read_csv("../../data/sens_scraped_new.csv")
    df = calculate_total_wallet_size(company_df=company, corporate_events_df=sens)