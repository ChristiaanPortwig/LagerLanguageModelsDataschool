"""
Prompts for LLMs
"""

COMPANY_LEVEL_PROMPT = """
You are extracting structured company-level financial and operational data from one document for ONE company.

The company is `{company}`. Always return that exact canonical JSE issuer name
in the `company` field. Never copy a longer legal name or an abbreviation from
the document.

The supplied documents may include:
- annual reports
- annual financial statements
- interim results
- results presentations

The response schema contains a list called `records`.

Create ONE record per distinct reporting period, not one record per document.
Merge information from multiple documents that refer to the same reporting period.

Rules:
- Extract only information explicitly stated in the supplied documents.
- Do not estimate, infer, or fabricate missing values.
- If a scalar field is not disclosed, return null.
- If a list field has no disclosed values, return an empty list.
- Return every value that can be represented numerically as a JSON number. Do
  not include currency symbols, thousands separators, percent signs or unit
  text in numeric fields.
- Keep monetary values at the scale printed in the source and set
  `reporting_unit` to exactly one of `units`, `thousands`, `millions` or
  `billions`. Normalize equivalent labels such as Rm, $m and mn to `millions`,
  and labels such as R'000 and £000 to `thousands`.
- Return `reporting_currency` and every item in `currencies_exposed_to` as an
  uppercase ISO 4217 three-letter code. For example, rand is ZAR, US dollars
  are USD and pounds sterling are GBP.
- Return `countries_of_operation` as sorted, unique ISO 3166-1 alpha-2 codes.
  For example, South Africa is ZA, the United Kingdom is GB and the United
  States is US.
- Return all dates in ISO 8601 `YYYY-MM-DD` format.
- Use percentage points for percentage fields and days for duration fields.
- Do not scale or convert monetary values.
- Prefer the most detailed and authoritative source where documents overlap.
- Do not duplicate a reporting period because the same information appears in an annual report, financial statements, and presentation.
- Use current-period values, not comparative prior-period values, unless the field specifically relates to future maturities or commitments.
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
- Return every value that can be represented numerically as a JSON number. Do
  not include currency symbols, thousands separators or unit text in numeric
  fields.
- `event_value` must only contain an explicitly disclosed monetary value at the
  scale printed in the source. Set `event_unit` to exactly one of `units`,
  `thousands`, `millions` or `billions`; normalize equivalent source labels.
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
