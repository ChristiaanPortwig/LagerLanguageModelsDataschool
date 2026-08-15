"""
Prompts for LLMs
"""

COMPANY_LEVEL_PROMPT = """
You are extracting structured company-level financial and operational data from one document for ONE company.

The company is `{company}`. Always return that exact canonical JSE issuer name
in the `company` field. Never copy a longer legal name or an abbreviation from
the document.

The supplied document may be one of the following:
- annual reports
- annual financial statements
- interim results
- results presentations

The response schema contains a list called `records`.

Create ONE record per distinct FULL-YEAR reporting period disclosed in this
document. Set `reporting_period_type` to `annual` for every returned record.

Do not return a record for a half-year, interim, quarterly, year-to-date, or
other partial period. A document whose primary subject is interim or half-year
results should normally return an empty `records` list. It may only yield a
record if it separately presents an explicitly labelled, complete full-year
period; use only the values belonging to that full-year period.

Rules:
- Extract only information explicitly stated in the supplied documents.
- Do not estimate, infer, or fabricate missing values.
- Never annualise a partial-period value. Never add H1 and H2, quarters,
  year-to-date amounts, or values from separate documents to manufacture an
  annual value.
- Never put a half-year or interim value into a full-year record, even when it
  is the newest value in the document.
- If a scalar field is not disclosed, return null.
- If a list field has no disclosed values, return an empty list.
- Return every value that can be represented numerically as a JSON number in
  scientific notation. For example, return 2.5e9 rather than 2,500 million,
  and 3.65e1 rather than 36.5. Do not include currency symbols, thousands
  separators, percent signs or unit text in numeric fields.
- Expand every monetary value to base units, regardless of the scale printed
  in the source. For example, R2.5 million must be returned as 2.5e6 and
  USD 3 billion as 3.0e9. Always set `reporting_unit` to `units`.
- Return `reporting_currency` and every item in `currencies_exposed_to` as an
  uppercase ISO 4217 three-letter code. For example, rand is ZAR, US dollars
  are USD and pounds sterling are GBP.
- Return `countries_of_operation` as sorted, unique ISO 3166-1 alpha-2 codes.
  For example, South Africa is ZA, the United Kingdom is GB and the United
  States is US.
- Return all dates in ISO 8601 `YYYY-MM-DD` format.
- Use percentage points for percentage fields and days for duration fields.
- Do not convert currencies. Only expand the source scale to base units.
- Prefer the most detailed and authoritative source where documents overlap.
- Do not duplicate a reporting period because the same information appears in an annual report, financial statements, and presentation.
- Within the selected full-year period, use values for that period rather than
  interim values or comparatives for another fiscal year. A prior-year annual
  comparative may be returned as its own annual record when it is explicit.
- Do not confuse total receivables/payables with trade receivables/payables.
- Do not infer imports, exports, foreign revenue, currencies, guarantees, derivatives, or exposures from general business descriptions.
- Only include countries, currencies, commodities, subsidiaries, customers, suppliers, lenders, or shareholders explicitly identified.
- For receivable days, payable days, inventory days, and cash conversion cycle, only populate them if explicitly disclosed. Otherwise return null.
- Debt maturity values must only be populated when the relevant maturity period is explicitly disclosed.
- For descriptive fields, summarise the disclosure concisely without adding interpretation.
- Use `extra_notes` for concise, evidence-based observations not captured by another field that may help Syn Bank target the company, such as stated strategic priorities, funding needs, operational changes, or relevant banking relationships.
- Do not repeat other fields in `extra_notes`; return null when there is no useful additional information.
- `source_document` should identify the main source used for that reporting-period record.
- `report_date` should be the reporting period end date.

The objective is accurate extraction for later share-of-wallet analysis.

Return only the structured output required by the schema.
"""


COMPANY_LEVEL_COMBINATION_PROMPT = """
You are reconciling candidate rows extracted independently from financial
documents for ONE company into the final company-level dataframe.

The company is `{company}`. Always return that exact canonical JSE issuer name
in the `company` field.

Candidate rows (JSON):
{records_json}

Return `record: null` when the candidates do not support a reliable full-year
annual record. Otherwise return exactly one final record for the most recent
full fiscal year supported by an annual report, annual financial statements,
or explicitly annual results.

Reconciliation rules:
- Decide which candidate value belongs in each field from its reporting period,
  source document, and meaning. Do not combine rows merely because a field is
  non-empty or newer.
- Set `reporting_period_type` to `annual`.
- Exclude every half-year, interim, quarterly, year-to-date, or other partial-
  period value. Never annualise, extrapolate, add, or otherwise manufacture a
  full-year value from partial periods.
- Keep all period-bound financial, cash-flow, debt, working-capital,
  expenditure, employee, market, and performance values aligned to the same
  selected fiscal year and `report_date`.
- Never fill a missing field using a value from another fiscal year. Missing is
  better than a plausible but mismatched value.
- You may combine complementary disclosures only when their sources clearly
  refer to the same selected annual reporting period.
- When same-period sources conflict, prefer audited annual financial statements,
  then the annual report, then explicitly annual results or presentations.
- Preserve list and descriptive disclosures only when they are supported by an
  annual source for the selected reporting cycle. Deduplicate list values.
- Do not convert currencies. Monetary values must remain expanded to base units
  and `reporting_unit` must be `units`.
- Use null for undisclosed scalar fields and an empty list for undisclosed list
  fields. Do not infer or fabricate values.
- `source_document` should concisely identify the principal annual source or
  sources used for the final record.

Return only the structured output required by the schema.
"""

SENS_PROMPT = """
You are analysing multiple SENS announcements for ONE company.

The company is `{company}`. Always return that exact canonical JSE issuer name
in the `company` field. Never copy a longer legal name or an abbreviation from
an announcement.

The response schema contains a list called `events`.

Create ONE event record per distinct material corporate event.

Rules:
- Extract only information supported by the supplied SENS announcements.
- Do not fabricate transaction values, dates, counterparties, countries, or deal details.
- If a scalar field is not disclosed, return null.
- If a list field has no relevant values, return an empty list.
- Ignore routine administrative announcements with no meaningful corporate-banking relevance.
- Do not create duplicate events when multiple announcements refer to the same underlying transaction or event. Use the most recent or most complete information where appropriate.
- Choose the event_type that best represents the underlying event.
- Use `other` only if none of the defined event types reasonably apply.
- Return every value that can be represented numerically as a JSON number in
  scientific notation. For example, return 2.5e9 rather than 2,500 million.
  Do not include currency symbols, thousands separators or unit text in
  numeric fields.
- `event_value` must only contain an explicitly disclosed monetary value,
  expanded to base units regardless of the scale printed in the source. For
  example, R2.5 million must be returned as 2.5e6. Set `event_unit` to `units`
  when `event_value` is present, otherwise set it to null.
- `currency` must correspond to `event_value` and must be an uppercase ISO 4217
  three-letter code. For example, rand is ZAR, US dollars are USD and pounds
  sterling are GBP.
- Return `country` as an ISO 3166-1 alpha-2 code, for example ZA, GB or US.
- Return all dates in ISO 8601 `YYYY-MM-DD` format.
- counterparty must only be populated when explicitly identified.
- expected_completion_date must only be populated when explicitly stated.
- banking_opportunities may contain multiple products, but include only products directly and reasonably connected to the disclosed event.
- Do not add banking products simply because they are theoretically possible.
- opportunity_summary should be concise and explain the direct commercial banking relevance.
- Use `extra_notes` for concise, evidence-based observations not captured by another field that may help Syn Bank target the company.
- Do not repeat other fields in `extra_notes`; return null when there is no useful additional information.
- source_document should identify the relevant SENS announcement.
- source_url should only be populated if supplied.

Relevant events include:
- acquisitions
- disposals
- new debt facilities
- refinancing
- bond issues
- equity raises
- major capex projects
- major contracts
- foreign expansion
- restructuring
- liquidity or covenant warnings
- dividends
- share buybacks
- guarantees or project obligations

Return only the structured output required by the schema.
"""


SENS_OPPORTUNITY_SCORING_PROMPT = """
You are rating the corporate-banking opportunities described by selected rows
from a SENS announcement dataframe.

Input rows (JSON):
{sens_json}

Return exactly one score record for every input row. Copy each `_row_id`
exactly into the response `row_id`. Do not omit, duplicate, or invent row IDs.

Give each row an independent opportunity score from 0 to 1 for each pillar:
- Transactional banking: payments, collections, liquidity management, trade
  finance, and guarantees.
- Global markets: foreign exchange, interest rates, and commodities.
- Investment banking: lending, debt and equity capital markets, corporate
  finance/advisory, and project finance.

Scoring rules:
- 0 means the announcement provides no evidence of an opportunity for that
  pillar; 1 means it provides direct evidence of an exceptionally strong and
  actionable opportunity.
- Base scores only on information in that row. Do not use outside knowledge or
  fabricate transaction values, funding needs, exposures, or mandates.
- Consider event type, value, currency, country, counterparties, dates,
  banking opportunities, the opportunity summary, and extra notes when present.
- A theoretically possible banking product is not enough for a high score.
  High scores require a direct, material, and actionable connection.
- Score all three pillars even when one or more scores are zero.

Return only the structured output required by the schema.
"""


DOCUMENT_FILENAME_VALIDATION_PROMPT = """
You are validating filenames of downloaded financial reports. The documents
belong to listed companies and will later be used for financial-data extraction.

Current calendar year: {current_year}
Previous calendar year: {previous_year}

Input documents:
{documents_json}

Return exactly one validation result for every input item. Copy `company` and
`filename` exactly; never invent, normalise, omit, or duplicate either value.

Set `is_explicitly_incorrect` to true only when the filename itself contains
clear, affirmative evidence of an error, such as:
- it explicitly names a different company;
- it explicitly names an unsupported document such as a transcript, script,
  Q&A, acquisition circular, trading statement, five-year review, or unrelated
  subsidiary report;
- it explicitly contains a year other than the current or previous calendar
  year; or
- its leading classification prefix explicitly contradicts the descriptive
  report type in the rest of the filename.

Set `is_explicitly_incorrect` to false for valid, generic, ambiguous, or
inconclusive filenames. A filename that lacks a company name, report type,
year, geographic reference, or other useful detail is generic, not incorrect.
Absence of evidence is never evidence of an error. Accept common abbreviations
such as AFS, IAR, IR, HY, H1 and FY. Underscores and URL-safe punctuation are
not errors.

Set `possibly_incorrect` to true only when the filename contains specific,
suspicious evidence of an error but the evidence is not conclusive. For
example, a filename may contain a named entity that could be an unrelated
company or subsidiary, or wording that could describe supporting material as
well as a valid report. Do not use `possibly_incorrect` merely because details
are absent. Generic filenames must have both flags set to false.

The two flags are mutually exclusive:
- explicit error: `is_explicitly_incorrect=true`, `possibly_incorrect=false`;
- suspicious but inconclusive: `is_explicitly_incorrect=false`,
  `possibly_incorrect=true`;
- valid, generic, or no specific evidence of an error: both false.

When either flag is true, `reason` must identify the explicit or suspicious
evidence found in the filename. Otherwise, `reason` should briefly state that
the filename is valid, generic, or inconclusive. Return only the structured
output required by the schema.
"""
