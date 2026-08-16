export function formatFieldName(value) {
  return String(value || '')
    .replace(/^_event_/, '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function overallConfidence(confidence = {}) {
  const levels = Object.values(confidence).map((item) => item?.level)
  if (!levels.length || levels.includes("can't estimate")) return "can't estimate"
  if (levels.includes('low')) return 'low'
  if (levels.includes('medium')) return 'medium'
  return 'high'
}
