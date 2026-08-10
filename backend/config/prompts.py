"""
Prompts for LLMs
"""

COMPANY_LEVEL_PROMPT = """
You are extracting structured company-level financial and operational data from multiple documents for ONE company.

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
- Preserve the reporting currency and reporting unit exactly as stated.
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
- `source_document` should identify the main source used for that reporting-period record.
- `report_date` should be the reporting period end date.

The objective is accurate extraction for later share-of-wallet analysis.

Return only the structured output required by the schema.
"""

SENS_PROMPT = """
You are analysing multiple SENS announcements for ONE company.

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
- event_value must only contain an explicitly disclosed monetary value.
- currency must correspond to event_value.
- counterparty must only be populated when explicitly identified.
- expected_completion_date must only be populated when explicitly stated.
- banking_opportunities may contain multiple products, but include only products directly and reasonably connected to the disclosed event.
- Do not add banking products simply because they are theoretically possible.
- opportunity_summary should be concise and explain the direct commercial banking relevance.
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