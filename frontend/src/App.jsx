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

function Nav({ view, onNavigate }) {
  return (
    <nav className="app-nav">
      <button
        type="button"
        className={`nav-tab ${view === 'table' ? 'active' : ''}`}
        onClick={() => onNavigate('table')}
      >
        Table
      </button>
      <button
        type="button"
        className={`nav-tab ${view === 'heatmap' ? 'active' : ''}`}
        onClick={() => onNavigate('heatmap')}
      >
        Heatmap
      </button>
    </nav>
  )
}

function ClientTable({ clients, onSelectClient }) {
  return (
    <>
      <h2 className="view-heading">Clients</h2>
      <p className="view-subtitle">
        All {clients.length} entities. Click a row for the full breakdown.
      </p>
      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th>Entity ID</th>
              <th>Entity Name</th>
              <th>Sector</th>
              <th className="numeric">Est. Total Wallet</th>
              <th className="numeric">Synthetic Bank Share</th>
              <th className="numeric">Opportunity Score</th>
            </tr>
          </thead>
          <tbody>
            {clients.map((client) => (
              <tr key={client.entity_id} onClick={() => onSelectClient(client.entity_id)}>
                <td>{client.entity_id}</td>
                <td className="entity-name">{client.entity_name}</td>
                <td className="sector">{client.sector}</td>
                <td className="numeric" title={formatZarFull(client.estimated_total_wallet_zar)}>
                  {formatZarAbbreviated(client.estimated_total_wallet_zar)}
                </td>
                <td className="numeric">{formatPercent(client.syn_bank_share_pct)}</td>
                <td className="numeric">{formatScore(client.opportunity_score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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

function OpportunityHeatmap({ clients, onSelectClient }) {
  const refinancing = clients.filter((c) => c.refinancing_flag)
  const notRefinancing = clients.filter((c) => !c.refinancing_flag)

  return (
    <>
      <h2 className="view-heading">Opportunity Heatmap</h2>
      <p className="view-subtitle">
        Wallet gap vs. opportunity score, colored by refinancing flag. Click a point for
        details.
      </p>
      <div className="panel chart-card">
        <ResponsiveContainer width="100%" height={480}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={CHART_INK.grid} />
            <XAxis
              type="number"
              dataKey="wallet_gap_zar"
              name="Wallet Gap (ZAR)"
              stroke={CHART_INK.axis}
              tick={{ fontSize: 12, fill: CHART_INK.axis }}
              tickFormatter={(v) => formatZarAbbreviated(v)}
            />
            <YAxis
              type="number"
              dataKey="opportunity_score"
              name="Opportunity Score"
              stroke={CHART_INK.axis}
              tick={{ fontSize: 12, fill: CHART_INK.axis }}
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
  { key: 'txn_banking_pct', label: 'Transactional Banking' },
  { key: 'cross_border_pct', label: 'Cross Border' },
  { key: 'trade_finance_pct', label: 'Trade Finance' },
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
    </>
  )
}

function App() {
  const [clients, setClients] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('table') // 'table' | 'heatmap' | 'detail'
  const [selectedEntityId, setSelectedEntityId] = useState(null)
  const [previousView, setPreviousView] = useState('table')

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
    setPreviousView(view)
    setSelectedEntityId(entityId)
    setView('detail')
  }

  const handleNavigate = (nextView) => {
    setView(nextView)
  }

  return (
    <div className="app-shell">
      <Header clientCount={clients.length || null} />
      {view !== 'detail' && <Nav view={view} onNavigate={handleNavigate} />}

      <div className="view-container">
        {loading && <p className="state-message">Loading clients...</p>}
        {error && <p className="state-message">Failed to load clients: {error}</p>}

        {!loading && !error && (
          <>
            {view === 'table' && (
              <ClientTable clients={clients} onSelectClient={handleSelectClient} />
            )}

            {view === 'heatmap' && (
              <OpportunityHeatmap clients={clients} onSelectClient={handleSelectClient} />
            )}

            {view === 'detail' && (
              <ClientDetail entityId={selectedEntityId} onBack={() => setView(previousView)} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default App
