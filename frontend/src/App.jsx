import { useEffect, useState } from 'react'
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
import { formatPercent, formatScore, formatZarAbbreviated, formatZarFull } from './format'

const API_BASE = 'http://localhost:4000/api/clients'

// Categorical palette, slots 1-2 (validated for scatter/all-pairs use in the
// dataviz skill's references/palette.md, mirroring the CSS tokens in
// index.css). refinancing_flag has only two values so it stays within the
// palette's validated series cap for scatter charts (sector, at 7 values,
// would exceed it).
const isDarkMode =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-color-scheme: dark)').matches
const REFI_COLORS = {
  true: isDarkMode ? '#d95926' : '#eb6834', // slot 2, orange
  false: isDarkMode ? '#3987e5' : '#2a78d6', // slot 1, blue
}
const CHART_INK = {
  grid: isDarkMode ? '#2c2c2a' : '#e1e0d9',
  axis: '#898781',
  surface: isDarkMode ? '#1a1a19' : '#fcfcfb',
}

function Header({ clientCount }) {
  return (
    <header className="app-header">
      <h1 className="app-title">Share of Wallet Dashboard</h1>
      {clientCount != null && (
        <span className="app-header-meta">{clientCount} corporate clients</span>
      )}
    </header>
  )
}

function PortfolioSummary({ clients }) {
  const totalClients = clients.length
  const avgShare = totalClients
    ? clients.reduce((sum, c) => sum + c.syn_bank_share_pct, 0) / totalClients
    : 0
  const totalWallet = clients.reduce((sum, c) => sum + c.estimated_total_wallet_zar, 0)
  const totalGap = clients.reduce((sum, c) => sum + c.wallet_gap_zar, 0)

  return (
    <>
      <h2 className="view-heading">Portfolio Summary</h2>
      <div className="panel kpi-panel">
        <div className="stat-grid">
          <div>
            <div className="stat-label">Total Clients</div>
            <div className="stat-value">{totalClients}</div>
          </div>
          <div>
            <div className="stat-label">Avg. Synthetic Bank Share</div>
            <div className="stat-value">{formatPercent(avgShare)}</div>
          </div>
          <div>
            <div className="stat-label">Total Estimated Wallet</div>
            <div className="stat-value" title={formatZarFull(totalWallet)}>
              {formatZarAbbreviated(totalWallet)}
            </div>
          </div>
          <div>
            <div className="stat-label">Total Wallet Gap</div>
            <div className="stat-value accent" title={formatZarFull(totalGap)}>
              {formatZarAbbreviated(totalGap)}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function ClientTable({ clients, onSelectClient, compact = false }) {
  const rows = compact
    ? [...clients].sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, 6)
    : clients

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
                <th>Sector</th>
                <th className="numeric">{compact ? 'Wallet' : 'Est. Total Wallet'}</th>
                <th className="numeric">{compact ? 'Syn. Share' : 'Synthetic Bank Share'}</th>
                <th className="numeric">{compact ? 'Score' : 'Opportunity Score'}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((client) => (
                <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                  <td>{client.entity_id}</td>
                  <td className="entity-name">{client.entity_name}</td>
                  <td className="sector">{client.sector}</td>
                  <td
                    className="numeric"
                    title={formatZarFull(client.estimated_total_wallet_zar)}
                  >
                    {formatZarAbbreviated(client.estimated_total_wallet_zar)}
                  </td>
                  <td className="numeric">{formatPercent(client.syn_bank_share_pct)}</td>
                  <td className="numeric">{formatScore(client.opportunity_score)}</td>
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

const PILLARS = [
  { key: 'syn_txn_banking_pct', label: 'Transactional Banking' },
  { key: 'syn_global_markets_pct', label: 'Global Markets' },
  { key: 'syn_trade_finance_pct', label: 'Trade Finance' },
  { key: 'lending_ib_pct', label: 'Lending / IB' },
]

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

function ProactiveFlags({ clients, onSelectClient, compact = false }) {
  const refinancingAll = clients
    .filter((c) => c.refinancing_flag)
    .sort((a, b) => a.refinancing_window_days - b.refinancing_window_days)
  const mismatchedAll = compact
    ? clients
        .filter((c) => c.import_mismatch_flag)
        .sort((a, b) => b.wallet_gap_zar - a.wallet_gap_zar)
    : clients.filter((c) => c.import_mismatch_flag)

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

function BriefingReport({ entityId }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleGenerate = () => {
    setLoading(true)
    setError(null)
    setReport(null)
    fetch(`${API_BASE}/${entityId}/briefing`, { method: 'POST' })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Request failed with status ${res.status}`)
        }
        return res.json()
      })
      .then((data) => setReport(data.report))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  return (
    <section className="panel detail-section">
      <h2>Briefing Report</h2>
      <button
        type="button"
        className="btn-primary"
        onClick={handleGenerate}
        disabled={loading}
      >
        {loading ? 'Generating…' : 'Generate Report'}
      </button>

      {loading && <p className="state-message state-message-inline">Generating report...</p>}
      {error && (
        <p className="state-message state-message-inline state-message-error">
          Failed to generate report: {error}
        </p>
      )}
      {report && !loading && !error && <p className="report-text">{report}</p>}
    </section>
  )
}

function ClientDetail({ entityId, onBack }) {
  const [client, setClient] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`${API_BASE}/${entityId}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Request failed with status ${res.status}`)
        }
        return res.json()
      })
      .then((data) => setClient(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [entityId])

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
          </div>
        </div>
      </section>

      <section className="panel detail-section">
        <h2>Pillar Breakdown</h2>
        {PILLARS.map(({ key, label }) => (
          <div className="pillar-row" key={key}>
            <div className="pillar-label">{label}</div>
            <div className="pillar-track">
              <div className="pillar-fill" style={{ width: `${client[key]}%` }} />
            </div>
            <div className="pillar-value">{formatPercent(client[key], 0)}</div>
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
          </div>
          <div className="flag-item">
            <div className="stat-label">Import Mismatch</div>
            <FlagBadge
              active={client.import_mismatch_flag}
              variant="serious"
              activeLabel="Mismatch detected"
              inactiveLabel="No mismatch detected"
            />
          </div>
        </div>
      </section>

      <BriefingReport key={client.entity_id} entityId={client.entity_id} />
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
      {children}
    </section>
  )
}

function App() {
  const [clients, setClients] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('grid') // 'grid' | 'detail'
  const [selectedEntityId, setSelectedEntityId] = useState(null)
  // Which of table/heatmap/flags is expanded, or null for the default grid.
  // Kept separate from `view` so opening a client's detail page and coming
  // back restores whichever panel was focused, instead of resetting it.
  const [focusedPanel, setFocusedPanel] = useState(null)

  useEffect(() => {
    fetch(API_BASE)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Request failed with status ${res.status}`)
        }
        return res.json()
      })
      .then((data) => setClients(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSelectClient = (entityId) => {
    setSelectedEntityId(entityId)
    setView('detail')
  }

  const handleCollapsePanel = () => setFocusedPanel(null)

  const refinancingCount = clients.filter((c) => c.refinancing_flag).length
  const mismatchCount = clients.filter((c) => c.import_mismatch_flag).length

  return (
    <div className="app-shell">
      {/* Reserved for the global prompt bar (added in a later step). */}
      <div className="prompt-bar-placeholder" aria-hidden="true" />

      <Header clientCount={clients.length || null} />

      <div className="view-container">
        {loading && <p className="state-message">Loading clients...</p>}
        {error && <p className="state-message">Failed to load clients: {error}</p>}

        {!loading && !error && (
          <>
            {view === 'grid' && (
              <div
                className={`dashboard-grid ${
                  focusedPanel ? `dashboard-grid--focus-${focusedPanel}` : ''
                }`}
              >
                <section className="grid-panel panel-summary">
                  <PortfolioSummary clients={clients} />
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
                  stripStat={`${refinancingCount} refinancing signals`}
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
                  stripStat={`${refinancingCount + mismatchCount} flags`}
                >
                  <ProactiveFlags
                    clients={clients}
                    onSelectClient={
                      focusedPanel === 'flags' ? handleSelectClient : () => setFocusedPanel('flags')
                    }
                    compact={focusedPanel !== 'flags'}
                  />
                </DashboardPanel>
              </div>
            )}

            {view === 'detail' && (
              <ClientDetail entityId={selectedEntityId} onBack={() => setView('grid')} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default App
