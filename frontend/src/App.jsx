import { Component, useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { API_ROOT, apiRequest } from './api'
import {
  ConfidenceBadge,
  ConfidenceDetails,
  DataQualityPage,
  DocumentUploadForm,
  FormulasPage,
  SettingsPage,
  WalletCalculation,
} from './features'
import { formatFieldName, overallConfidence } from './featureFormat'
import { formatPercent, formatScore, formatZarAbbreviated, formatZarFull } from './format'

// Categorical palette, slots 1-2 - Standard Bank blue + a warm complement,
// re-validated for scatter/all-pairs use with the dataviz skill's
// validate_palette.js (six-checks, both modes), mirroring the CSS tokens in
// index.css. refinancing_flag has only two values so it stays within the
// palette's validated series cap for scatter charts (sector, at 7 values,
// would exceed it).
const isDarkMode =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-color-scheme: dark)').matches
const REFI_COLORS = {
  true: isDarkMode ? '#c9682f' : '#c1622e', // slot 2, warm terracotta
  false: isDarkMode ? '#2f8fe0' : '#005199', // slot 1, Standard Bank blue
}
const CHART_INK = {
  grid: isDarkMode ? '#2c2c2a' : '#e1e0d9',
  axis: '#898781',
  surface: isDarkMode ? '#1a1a19' : '#fcfcfb',
}

// Keeps a crash in one panel (e.g. a schema mismatch against the API) from
// unmounting the entire dashboard. Catches render/lifecycle errors in its
// subtree only - does not catch errors from event handlers or async code.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error(`${this.props.label || 'A panel'} failed to render:`, error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <p className="state-message state-message-error">
          {this.props.label || 'This panel'} failed to render ({this.state.error.message}).
        </p>
      )
    }
    return this.props.children
  }
}

function Header({ clientCount, view, onNavigate }) {
  const links = [
    ['grid', 'Dashboard'],
    ['data', 'Data gaps'],
    ['formulas', 'Formulas'],
    ['settings', 'Settings'],
  ]
  return (
    <header className="app-header">
      <h1 className="app-title">Share of Wallet Dashboard</h1>
      <div className="header-actions">
        <nav className="app-nav" aria-label="Main navigation">
          {links.map(([key, label]) => (
            <button
              type="button"
              key={key}
              className={view === key ? 'active' : ''}
              onClick={() => onNavigate(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        {clientCount != null && (
          <span className="app-header-meta">{clientCount} corporate clients</span>
        )}
      </div>
    </header>
  )
}

function PortfolioSummary({ summary }) {
  return (
    <>
      <h2 className="view-heading">Portfolio Summary</h2>
      <div className="panel kpi-panel">
        <div className="stat-grid">
          <div>
            <div className="stat-label">Total Clients</div>
            <div className="stat-value">{summary.total_clients}</div>
          </div>
          <div>
            <div className="stat-label">Avg. Synthetic Bank Share</div>
            <div className="stat-value">{formatPercent(summary.average_syn_bank_share_pct)}</div>
          </div>
          <div>
            <div className="stat-label">Total Estimated Wallet</div>
            <div className="stat-value" title={formatZarFull(summary.total_estimated_wallet_zar)}>
              {formatZarAbbreviated(summary.total_estimated_wallet_zar)}
            </div>
          </div>
          <div>
            <div className="stat-label">Total Wallet Gap</div>
            <div className="stat-value accent" title={formatZarFull(summary.total_wallet_gap_zar)}>
              {formatZarAbbreviated(summary.total_wallet_gap_zar)}
            </div>
          </div>
          <div>
            <div className="stat-label">Engage Now</div>
            <div className="stat-value accent">{summary.engage_now_count || 0}</div>
          </div>
        </div>
      </div>
    </>
  )
}

function ReportAction({ client, onChanged }) {
  const [report, setReport] = useState(client.report || { available: false })
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setReport(client.report || { available: false })
  }, [client.report])

  const generate = async (event) => {
    event.stopPropagation()
    setGenerating(true)
    setError(null)
    try {
      const status = await apiRequest(`/clients/${client.entity_id}/report`, {
        method: 'POST',
      })
      setReport(status)
      onChanged?.()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setGenerating(false)
    }
  }

  if (report.available) {
    return (
      <a
        className="btn-secondary report-action"
        href={`${API_ROOT}/clients/${client.entity_id}/report/download`}
        download={report.filename}
        onClick={(event) => event.stopPropagation()}
        title={report.generated_at ? `Generated ${new Date(report.generated_at).toLocaleString('en-ZA')}` : ''}
      >
        Download report
      </a>
    )
  }

  return (
    <span className="report-action-wrap">
      <button type="button" className="btn-primary report-action" onClick={generate} disabled={generating}>
        {generating ? 'Generating…' : 'Generate report'}
      </button>
      {error && <span className="report-action-error" title={error}>Failed</span>}
    </span>
  )
}

function ClientTable({ clients, onSelectClient, onSelectConfidence, onReportChanged, compact = false }) {
  const orderedClients = [...clients].sort(
    (a, b) => (b.opportunity_score || 0) - (a.opportunity_score || 0)
      || a.entity_id.localeCompare(b.entity_id),
  )
  const rows = compact ? orderedClients.slice(0, 6) : orderedClients

  return (
    <>
      <h2 className="view-heading">Clients</h2>
      <p className="view-subtitle">
        {compact
          ? `Top ${rows.length} by opportunity score. Click a row for the full breakdown.`
          : `All ${clients.length} entities. Click a row for the full breakdown.`}
      </p>
      <div className="panel">
        <div className="table-scroll">
          <table className={`data-table ${compact ? 'data-table-compact' : ''}`}>
            <thead>
              <tr>
                <th>Entity ID</th>
                <th>Entity Name</th>
                <th>Relationship Manager</th>
                <th>Sector</th>
                <th className="numeric">{compact ? 'Wallet' : 'Est. Total Wallet'}</th>
                <th className="numeric">{compact ? 'Syn. Share' : 'Synthetic Bank Share'}</th>
                <th className="numeric">{compact ? 'Score' : 'Opportunity Score'}</th>
                {!compact && <th>Next Payment</th>}
                {!compact && <th>Engage</th>}
                <th>Confidence</th>
                <th>Report</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((client) => (
                <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                  <td>{client.entity_id}</td>
                  <td className="entity-name">{client.entity_name}</td>
                  <td>{client.relationship_manager?.name || 'Unassigned'}</td>
                  <td className="sector">{client.sector}</td>
                  <td
                    className="numeric"
                    title={formatZarFull(client.estimated_total_wallet_zar)}
                  >
                    {formatZarAbbreviated(client.estimated_total_wallet_zar)}
                  </td>
                  <td className="numeric">{formatPercent(client.syn_bank_share_pct)}</td>
                  <td className="numeric">{formatScore(client.opportunity_score)}</td>
                  {!compact && (
                    <td>{formatTimingDate(client.timing_intelligence?.payment_timing?.predicted_payment_date)}</td>
                  )}
                  {!compact && (
                    <td>
                      {client.timing_intelligence?.engagement_prediction?.engage_now
                        ? <span className="badge badge-serious">Engage now</span>
                        : formatTimingDate(
                          client.timing_intelligence?.engagement_prediction
                            ?.recommended_engagement_date,
                        )}
                    </td>
                  )}
                  <td>
                    <ConfidenceBadge
                      level={overallConfidence(client.confidence)}
                      onClick={(event) => {
                        event.stopPropagation()
                        onSelectConfidence(client.entity_id, 'confidence')
                      }}
                    />
                  </td>
                  <td>
                    <ReportAction client={client} onChanged={onReportChanged} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

function HeatmapTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const client = payload[0].payload
  return (
    <div className="chart-tooltip">
      <strong>
        {client.entity_name} ({client.entity_id})
      </strong>
      <div>Sector: {client.sector}</div>
      <div>Wallet gap: {formatZarAbbreviated(client.wallet_gap_zar)}</div>
      <div>Opportunity score: {formatScore(client.opportunity_score)}</div>
      <div>Refinancing flag: {String(client.refinancing_flag)}</div>
    </div>
  )
}

function OpportunityHeatmap({ clients, onSelectClient, compact = false }) {
  const refinancing = clients.filter((c) => c.refinancing_flag)
  const notRefinancing = clients.filter((c) => !c.refinancing_flag)
  const height = compact ? 240 : 480
  const tickFontSize = compact ? 11 : 12

  return (
    <>
      <h2 className="view-heading">Opportunity Heatmap</h2>
      {!compact && (
        <p className="view-subtitle">
          Wallet gap vs. opportunity score, colored by refinancing flag. Click a point for
          details.
        </p>
      )}
      <div className={`panel chart-card ${compact ? 'chart-card-compact' : ''}`}>
        <ResponsiveContainer width="100%" height={height}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={CHART_INK.grid} />
            <XAxis
              type="number"
              dataKey="wallet_gap_zar"
              name="Wallet Gap (ZAR)"
              stroke={CHART_INK.axis}
              tick={{ fontSize: tickFontSize, fill: CHART_INK.axis }}
              tickFormatter={(v) => formatZarAbbreviated(v)}
            />
            <YAxis
              type="number"
              dataKey="opportunity_score"
              name="Opportunity Score"
              stroke={CHART_INK.axis}
              tick={{ fontSize: tickFontSize, fill: CHART_INK.axis }}
            />
            <Tooltip
              cursor={{ strokeDasharray: '3 3', stroke: CHART_INK.axis }}
              content={<HeatmapTooltip />}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            <Scatter
              name="Refinancing: false"
              data={notRefinancing}
              fill={REFI_COLORS.false}
              onClick={(point) => onSelectClient(point.entity_id)}
              cursor="pointer"
            />
            <Scatter
              name="Refinancing: true"
              data={refinancing}
              fill={REFI_COLORS.true}
              onClick={(point) => onSelectClient(point.entity_id)}
              cursor="pointer"
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

function FlagBadge({ active, variant, activeLabel, inactiveLabel }) {
  if (active) {
    return (
      <span className={`badge badge-${variant}`}>
        ⚠ {activeLabel}
      </span>
    )
  }
  return <span className="badge badge-neutral">{inactiveLabel}</span>
}

function ProactiveFlags({ flags, onSelectClient, compact = false }) {
  const engagementsAll = flags.engagements || []
  const refinancingAll = flags.refinancing
  // The API's import_trade_finance_gaps array carries flat fields
  // (import_mismatch_flag, wallet_gap_zar) rather than a nested
  // import_trade_finance_gap object - filter defensively rather than
  // assume every entry is already flagged.
  const mismatchedAll = (flags.import_trade_finance_gaps || []).filter(
    (c) => c.import_mismatch_flag,
  )

  const engagements = compact ? engagementsAll.slice(0, 3) : engagementsAll
  const refinancing = compact ? refinancingAll.slice(0, 3) : refinancingAll
  const mismatched = compact ? mismatchedAll.slice(0, 3) : mismatchedAll

  return (
    <>
      <h2 className="view-heading">Proactive Flags</h2>
      {!compact && (
        <p className="view-subtitle">
          Clients that need outreach this week - sorted by urgency, not alphabetically.
        </p>
      )}

      <h3 className="section-heading">
        Payment &amp; Engagement Timing
        {compact && engagementsAll.length > engagements.length && (
          <span className="section-heading-count">
            {' '}
            · next {engagements.length} of {engagementsAll.length}
          </span>
        )}
      </h3>
      <div className="panel">
        {engagements.length === 0 ? (
          <p className="state-message">No payment timing is currently available.</p>
        ) : (
          <div className="table-scroll">
            <table className={`data-table ${compact ? 'data-table-compact' : ''}`}>
              <thead>
                <tr>
                  <th>Entity Name</th>
                  <th>Engagement</th>
                  <th>Next Payment</th>
                  {!compact && <th>Strategy</th>}
                </tr>
              </thead>
              <tbody>
                {engagements.map((client) => {
                  const timing = client.timing_intelligence || {}
                  const engagement = timing.engagement_prediction || {}
                  return (
                    <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                      <td className="entity-name">{client.entity_name}</td>
                      <td>
                        {engagement.engage_now ? (
                          <span className="badge badge-serious">Engage now</span>
                        ) : formatTimingDate(engagement.recommended_engagement_date)}
                      </td>
                      <td>{formatTimingDate(timing.payment_timing?.predicted_payment_date)}</td>
                      {!compact && <td>{timing.payment_timing?.strategy || 'General Coverage'}</td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <h3 className="section-heading">
        Refinancing Opportunities
        {compact && refinancingAll.length > refinancing.length && (
          <span className="section-heading-count">
            {' '}
            · top {refinancing.length} of {refinancingAll.length}
          </span>
        )}
      </h3>
      <div className="panel">
        {refinancing.length === 0 ? (
          <p className="state-message">No refinancing windows currently flagged.</p>
        ) : (
          <div className="table-scroll">
            <table className={`data-table ${compact ? 'data-table-compact' : ''}`}>
              <thead>
                <tr>
                  <th>Entity Name</th>
                  <th>Sector</th>
                  <th>Status</th>
                  <th className="numeric">Est. Total Wallet</th>
                </tr>
              </thead>
              <tbody>
                {refinancing.map((client) => (
                  <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                    <td className="entity-name">{client.entity_name}</td>
                    <td className="sector">{client.sector}</td>
                    <td>
                      <FlagBadge
                        active
                        variant="warning"
                        activeLabel={`Window: ${client.refinancing_window_days} days`}
                      />
                    </td>
                    <td
                      className="numeric"
                      title={formatZarFull(client.estimated_total_wallet_zar)}
                    >
                      {formatZarAbbreviated(client.estimated_total_wallet_zar)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <h3 className="section-heading">
        Import / Trade Finance Gaps
        {compact && mismatchedAll.length > mismatched.length && (
          <span className="section-heading-count">
            {' '}
            · top {mismatched.length} of {mismatchedAll.length}
          </span>
        )}
      </h3>
      <div className="panel">
        {mismatched.length === 0 ? (
          <p className="state-message">No import mismatches currently flagged.</p>
        ) : (
          <div className="table-scroll">
            <table className={`data-table ${compact ? 'data-table-compact' : ''}`}>
              <thead>
                <tr>
                  <th>Entity Name</th>
                  <th>Sector</th>
                  <th>Status</th>
                  <th className="numeric">Wallet Gap</th>
                </tr>
              </thead>
              <tbody>
                {mismatched.map((client) => (
                  <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                    <td className="entity-name">{client.entity_name}</td>
                    <td className="sector">{client.sector}</td>
                    <td>
                      <FlagBadge active variant="serious" activeLabel="Mismatch detected" />
                    </td>
                    <td className="numeric" title={formatZarFull(client.wallet_gap_zar)}>
                      {formatZarAbbreviated(client.wallet_gap_zar)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}

function formatTimingDate(value) {
  if (!value) return 'Not available'
  return new Date(`${value}T00:00:00`).toLocaleDateString('en-ZA', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function TimingIntelligence({ timing, error }) {
  if (error && !timing) {
    return <p className="state-message state-message-inline state-message-error">{error}</p>
  }
  if (!timing) {
    return <p className="state-message state-message-inline">No payment timing is available.</p>
  }

  const cashIn = timing.cash_cycle?.cash_in || {}
  const cashOut = timing.cash_cycle?.cash_out || {}
  const payment = timing.payment_timing || {}
  const engagement = timing.engagement_prediction || {}
  const windowText = (cycle) => cycle.peak_day == null
    ? 'Not available'
    : `Day ${cycle.window_start_day}–${cycle.window_end_day}`

  return (
    <>
      <div className="timing-grid">
        <div className="timing-card">
          <div className="stat-label">Cash-in cycle</div>
          <div className="timing-value">{windowText(cashIn)}</div>
          <p>
            Peak day {cashIn.peak_day ?? '—'} · {cashIn.confidence_pct == null
              ? 'No confidence estimate'
              : `${formatPercent(cashIn.confidence_pct)} of value in window`}
          </p>
        </div>
        <div className="timing-card">
          <div className="stat-label">Cash-out cycle</div>
          <div className="timing-value">{windowText(cashOut)}</div>
          <p>
            Peak day {cashOut.peak_day ?? '—'} · {cashOut.confidence_pct == null
              ? 'No confidence estimate'
              : `${formatPercent(cashOut.confidence_pct)} of value in window`}
          </p>
        </div>
        <div className="timing-card">
          <div className="stat-label">Next predicted payment</div>
          <div className="timing-value">{formatTimingDate(payment.predicted_payment_date)}</div>
          <p>
            {payment.strategy || 'General Coverage'} · {payment.confidence_band || 'Low'} confidence
          </p>
        </div>
      </div>

      <div className={`engagement-callout ${engagement.engage_now ? 'engagement-callout-now' : ''}`}>
        <div className="engagement-heading">
          <div>
            <div className="stat-label">
              {engagement.generated_by === 'gemini' ? 'Gemini engagement prediction' : 'Engagement prediction'}
            </div>
            <div className="timing-value">
              {engagement.engage_now
                ? 'Engage now'
                : formatTimingDate(engagement.recommended_engagement_date)}
            </div>
          </div>
          <span className={`badge ${engagement.engage_now ? 'badge-serious' : 'badge-neutral'}`}>
            {engagement.engagement_priority || 'Low'} priority
          </span>
        </div>
        <p>{engagement.rationale}</p>
        <strong>{engagement.recommended_action}</strong>
        {engagement.generated_by === 'rules_fallback' && (
          <small>Rules fallback shown because a Gemini prediction was not available.</small>
        )}
      </div>
    </>
  )
}

function ClientDetail({ entityId, onBack, initialSection, onClientChanged }) {
  const [client, setClient] = useState(null)
  const [calculation, setCalculation] = useState(null)
  const [timing, setTiming] = useState(null)
  const [timingError, setTimingError] = useState(null)
  const [missingDocuments, setMissingDocuments] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)

  const loadCalculation = () =>
    apiRequest(`/clients/${entityId}/calculation`).then(setCalculation)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setTimingError(null)
    Promise.all([
      apiRequest(`/clients/${entityId}`),
      apiRequest(`/clients/${entityId}/calculation`),
      apiRequest('/missing-data'),
      apiRequest(`/clients/${entityId}/payment-timing`).catch((requestError) => {
        setTimingError(`Payment timing could not be loaded: ${requestError.message}`)
        return null
      }),
    ])
      .then(([clientData, calculationData, missingData, timingData]) => {
        setClient(clientData)
        setCalculation(calculationData)
        setTiming(timingData || clientData.timing_intelligence || null)
        setMissingDocuments(
          missingData.documents.filter((item) => item.company === clientData.entity_name),
        )
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [entityId])

  useEffect(() => {
    if (!loading && initialSection) {
      document.getElementById(initialSection)?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [initialSection, loading])

  if (loading) return <p className="state-message">Loading client...</p>
  if (error) return <p className="state-message">Failed to load client: {error}</p>
  if (!client) return null

  return (
    <>
      <button type="button" className="back-link" onClick={onBack}>
        &larr; Back
      </button>

      <div className="detail-header">
        <h2 className="view-heading">{client.entity_name}</h2>
        <span className="entity-id">{client.entity_id}</span>
      </div>
      <span className="detail-sector-tag">{client.sector}</span>

      <section className="panel detail-section">
        <h2>Overview</h2>
        <div className="stat-grid">
          <div>
            <div className="stat-label">Estimated Total Wallet</div>
            <div className="stat-value" title={formatZarFull(client.estimated_total_wallet_zar)}>
              {formatZarAbbreviated(client.estimated_total_wallet_zar)}
            </div>
          </div>
          <div>
            <div className="stat-label">Synthetic Bank Share</div>
            <div className="stat-value">{formatPercent(client.syn_bank_share_pct)}</div>
          </div>
          <div>
            <div className="stat-label">Wallet Gap</div>
            <div className="stat-value" title={formatZarFull(client.wallet_gap_zar)}>
              {formatZarAbbreviated(client.wallet_gap_zar)}
            </div>
          </div>
          <div>
            <div className="stat-label">Opportunity Score</div>
            <div className="stat-value accent">{formatScore(client.opportunity_score)}</div>
            <ConfidenceBadge
              level={overallConfidence(calculation?.confidence)}
              onClick={() => document.getElementById('confidence')?.scrollIntoView({ behavior: 'smooth' })}
            />
          </div>
          <div>
            <div className="stat-label">Relationship Manager</div>
            <div className="stat-value relationship-manager-name">
              {client.relationship_manager?.name || 'Unassigned'}
            </div>
            <div className="manager-meta">
              {client.relationship_manager?.title}
              {client.relationship_manager?.email && ` · ${client.relationship_manager.email}`}
            </div>
            {client.relationship_manager?.is_mock && (
              <span className="badge badge-neutral">Mock directory</span>
            )}
          </div>
        </div>
      </section>

      <section className="panel detail-section">
        <h2>Cash Cycle &amp; Payment Timing</h2>
        <TimingIntelligence timing={timing} error={timingError} />
      </section>

      <section className="panel detail-section" id="confidence">
        <h2>Score Confidence</h2>
        <ConfidenceDetails
          entityId={entityId}
          calculation={calculation}
          onDataSaved={(updated) => {
            setClient(updated)
            loadCalculation()
            onClientChanged?.()
          }}
        />
      </section>

      <section className="panel detail-section">
        <h2>Pillar Breakdown</h2>
        {(client.pillar_breakdown || []).map(({ key, label, value }) => (
          <div className="pillar-row" key={key}>
            <div className="pillar-label">{label}</div>
            <div className="pillar-track">
              <div className="pillar-fill" style={{ width: `${value}%` }} />
            </div>
            <div className="pillar-value">{formatPercent(value, 0)}</div>
          </div>
        ))}
      </section>

      <section className="panel detail-section">
        <h2>Flags</h2>
        <div className="flags-grid">
          <div className="flag-item">
            <div className="stat-label">Refinancing</div>
            <FlagBadge
              active={client.refinancing_flag}
              variant="warning"
              activeLabel={`Window: ${client.refinancing_window_days} days`}
              inactiveLabel="No refinancing signal"
            />
            <p className="flag-reason">{client.refinancing_opportunity?.reason}</p>
          </div>
          <div className="flag-item">
            <div className="stat-label">Import Mismatch</div>
            <FlagBadge
              active={client.import_mismatch_flag}
              variant="serious"
              activeLabel="Mismatch detected"
              inactiveLabel="No mismatch detected"
            />
            <p className="flag-reason">{client.import_trade_finance_gap?.reason}</p>
          </div>
          <div className="flag-item">
            <div className="stat-label">Missing PDFs</div>
            <FlagBadge
              active={missingDocuments.length > 0}
              variant="warning"
              activeLabel={`${missingDocuments.length} document${missingDocuments.length === 1 ? '' : 's'} missing`}
              inactiveLabel="Current PDFs available"
            />
          </div>
        </div>
        {missingDocuments.length > 0 && (
          <div className="document-flags">
            {missingDocuments.map((document) => (
              <span className="field-chip-static" key={document.document_type}>
                {formatFieldName(document.document_type)}
              </span>
            ))}
            <button type="button" className="text-button" onClick={() => setShowUpload(!showUpload)}>
              {showUpload ? 'Close upload' : 'Upload missing PDF'}
            </button>
          </div>
        )}
        {showUpload && (
          <div className="nested-form">
            <DocumentUploadForm
              entityId={entityId}
              initialType={missingDocuments[0]?.document_type}
              onCancel={() => setShowUpload(false)}
              onUploaded={() => setShowUpload(false)}
            />
          </div>
        )}
      </section>

      <section className="panel detail-section">
        <h2>Wallet Calculation</h2>
        <WalletCalculation calculation={calculation?.wallet_calculation} />
      </section>

      <section className="panel detail-section">
        <h2>Client Report</h2>
        <ReportAction client={client} onChanged={onClientChanged} />
        <p className="view-subtitle">The downloadable report includes the Gemini briefing and a separate formulas page.</p>
      </section>
    </>
  )
}

/**
 * Wraps one of the three interactive dashboard panels (table/heatmap/flags)
 * and handles its three possible states, keeping the same grid slot in every
 * state so only the panel's own content/size changes, not its DOM position:
 *
 *   - default: no panel is focused. Renders the normal (compact) tile;
 *     clicking anywhere on it focuses this panel.
 *   - focused: this panel is the one in focus. Renders full content plus a
 *     "Collapse" control to return to the default grid.
 *   - strip: a different panel is focused. Renders a thin clickable strip
 *     (title + one stat) that switches focus to this panel instead.
 */
function DashboardPanel({
  panelKey,
  focusedPanel,
  onFocus,
  onCollapse,
  stripTitle,
  stripStat,
  children,
}) {
  const isFocused = focusedPanel === panelKey
  const isStrip = focusedPanel !== null && !isFocused

  if (isStrip) {
    return (
      <section className={`grid-panel panel-${panelKey} panel-strip-wrap`}>
        <button type="button" className="panel-strip" onClick={() => onFocus(panelKey)}>
          <span className="panel-strip-title">{stripTitle}</span>
          {stripStat && <span className="panel-strip-stat">{stripStat}</span>}
        </button>
      </section>
    )
  }

  return (
    <section
      className={`grid-panel panel-${panelKey} ${isFocused ? 'panel-focused' : 'panel-clickable'}`}
      onClick={!isFocused ? () => onFocus(panelKey) : undefined}
    >
      {isFocused && (
        <button
          type="button"
          className="panel-collapse-btn"
          onClick={(event) => {
            event.stopPropagation()
            onCollapse()
          }}
        >
          Collapse ✕
        </button>
      )}
      <ErrorBoundary label={stripTitle}>{children}</ErrorBoundary>
    </section>
  )
}

function App() {
  const [clients, setClients] = useState([])
  const [summary, setSummary] = useState(null)
  const [proactiveFlags, setProactiveFlags] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('grid')
  const [selectedEntityId, setSelectedEntityId] = useState(null)
  const [detailSection, setDetailSection] = useState(null)
  // Which of table/heatmap/flags is expanded, or null for the default grid.
  // Kept separate from `view` so opening a client's detail page and coming
  // back restores whichever panel was focused, instead of resetting it.
  const [focusedPanel, setFocusedPanel] = useState(null)

  const loadDashboard = () => {
    setError(null)
    return apiRequest('/dashboard')
      .then((data) => {
        setClients(data.clients)
        setSummary(data.summary)
        setProactiveFlags(data.proactive_flags)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadDashboard()
    const refresh = window.setInterval(loadDashboard, 30000)
    return () => window.clearInterval(refresh)
  }, [])

  const handleSelectClient = (entityId, section = null) => {
    setSelectedEntityId(entityId)
    setDetailSection(section)
    setView('detail')
  }

  const handleNavigate = (nextView) => {
    setView(nextView)
    setDetailSection(null)
  }

  const handleCollapsePanel = () => setFocusedPanel(null)

  return (
    <div className="app-shell">
      <Header
        clientCount={summary?.total_clients || null}
        view={view}
        onNavigate={handleNavigate}
      />

      <div className="view-container">
        {loading && <p className="state-message">Loading clients...</p>}
        {error && <p className="state-message">Failed to load clients: {error}</p>}

        {!loading && !error && summary && proactiveFlags && (
          <ErrorBoundary key={view} label="This view">
            {view === 'grid' && (
              <div
                className={`dashboard-grid ${
                  focusedPanel ? `dashboard-grid--focus-${focusedPanel}` : ''
                }`}
              >
                <section className="grid-panel panel-summary">
                  <ErrorBoundary label="Portfolio Summary">
                    <PortfolioSummary summary={summary} />
                  </ErrorBoundary>
                </section>

                <DashboardPanel
                  panelKey="table"
                  focusedPanel={focusedPanel}
                  onFocus={setFocusedPanel}
                  onCollapse={handleCollapsePanel}
                  stripTitle="Clients"
                  stripStat={`${clients.length} total`}
                >
                  <ClientTable
                    clients={clients}
                    onSelectConfidence={handleSelectClient}
                    onReportChanged={loadDashboard}
                    onSelectClient={
                      focusedPanel === 'table' ? handleSelectClient : () => setFocusedPanel('table')
                    }
                    compact={focusedPanel !== 'table'}
                  />
                </DashboardPanel>

                <DashboardPanel
                  panelKey="heatmap"
                  focusedPanel={focusedPanel}
                  onFocus={setFocusedPanel}
                  onCollapse={handleCollapsePanel}
                  stripTitle="Opportunity Heatmap"
                  stripStat={`${summary.refinancing_flag_count} refinancing signals`}
                >
                  <OpportunityHeatmap
                    clients={clients}
                    onSelectClient={
                      focusedPanel === 'heatmap'
                        ? handleSelectClient
                        : () => setFocusedPanel('heatmap')
                    }
                    compact={focusedPanel !== 'heatmap'}
                  />
                </DashboardPanel>

                <DashboardPanel
                  panelKey="flags"
                  focusedPanel={focusedPanel}
                  onFocus={setFocusedPanel}
                  onCollapse={handleCollapsePanel}
                  stripTitle="Proactive Flags"
                  stripStat={`${summary.total_flag_count} flags`}
                >
                  <ProactiveFlags
                    flags={proactiveFlags}
                    onSelectClient={
                      focusedPanel === 'flags' ? handleSelectClient : () => setFocusedPanel('flags')
                    }
                    compact={focusedPanel !== 'flags'}
                  />
                </DashboardPanel>
              </div>
            )}

            {view === 'detail' && (
              <ClientDetail
                entityId={selectedEntityId}
                initialSection={detailSection}
                onClientChanged={loadDashboard}
                onBack={() => setView('grid')}
              />
            )}

            {view === 'data' && (
              <DataQualityPage clients={clients} onClientsChanged={loadDashboard} />
            )}

            {view === 'formulas' && <FormulasPage />}

            {view === 'settings' && <SettingsPage onClientsChanged={loadDashboard} />}
          </ErrorBoundary>
        )}
      </div>
    </div>
  )
}

export default App
