// Formatting helpers for the share-of-wallet dashboard. Kept plain (no
// libraries) since the values are already numbers from the API.

/** R63.4B / R382M / R1.2K style abbreviation for large ZAR amounts. */
export function formatZarAbbreviated(value) {
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${sign}R${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}R${(abs / 1e6).toFixed(0)}M`
  if (abs >= 1e3) return `${sign}R${(abs / 1e3).toFixed(0)}K`
  return `${sign}R${abs.toFixed(0)}`
}

/** Full ZAR amount with thousands separators, for tooltips/title attrs. */
export function formatZarFull(value) {
  return `R${Math.round(value).toLocaleString('en-ZA')}`
}

/** Percentage with a fixed, consistent decimal count. */
export function formatPercent(value, decimals = 1) {
  return `${value.toFixed(decimals)}%`
}

/** Plain 0-100 score, not a percentage. */
export function formatScore(value) {
  return value.toFixed(1)
}
