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

const API_BASE = 'http://localhost:4000/api/clients'

// Categorical palette, slots 1-2 (validated for scatter/all-pairs use in
// dataviz skill's references/palette.md) - refinancing_flag has only two
// values so it stays within the palette's validated series cap for scatter
// charts (sector, at 7 values, would exceed it).
const REFI_COLORS = {
  true: '#eb6834', // slot 2, orange
  false: '#2a78d6', // slot 1, blue
}

function Nav({ view, onNavigate }) {
  return (
    <nav>
      <button
        type="button"
        onClick={() => onNavigate('table')}
        disabled={view === 'table'}
      >
        Table
      </button>{' '}
      <button
        type="button"
        onClick={() => onNavigate('heatmap')}
        disabled={view === 'heatmap'}
      >
        Heatmap
      </button>
    </nav>
  )
}

function ClientTable({ clients, onSelectClient }) {
  return (
    <>
      <h1>Share of Wallet - Clients</h1>
      <table>
        <thead>
          <tr>
            <th>Entity ID</th>
            <th>Entity Name</th>
            <th>Sector</th>
            <th>Estimated Total Wallet (ZAR)</th>
            <th>Synthetic Bank Share (%)</th>
            <th>Opportunity Score</th>
          </tr>
        </thead>
        <tbody>
          {clients.map((client) => (
            <tr
              key={client.entity_id}
              onClick={() => onSelectClient(client.entity_id)}
              style={{ cursor: 'pointer' }}
            >
              <td>{client.entity_id}</td>
              <td>{client.entity_name}</td>
              <td>{client.sector}</td>
              <td>{client.estimated_total_wallet_zar}</td>
              <td>{client.syn_bank_share_pct}</td>
              <td>{client.opportunity_score}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function HeatmapTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const client = payload[0].payload
  return (
    <div
      style={{
        background: '#fcfcfb',
        border: '1px solid #c3c2b7',
        padding: '8px',
      }}
    >
      <strong>
        {client.entity_name} ({client.entity_id})
      </strong>
      <div>Sector: {client.sector}</div>
      <div>Wallet Gap (ZAR): {client.wallet_gap_zar}</div>
      <div>Opportunity Score: {client.opportunity_score}</div>
      <div>Refinancing Flag: {String(client.refinancing_flag)}</div>
    </div>
  )
}

function OpportunityHeatmap({ clients, onSelectClient }) {
  const refinancing = clients.filter((c) => c.refinancing_flag)
  const notRefinancing = clients.filter((c) => !c.refinancing_flag)

  return (
    <>
      <h1>Opportunity Heatmap</h1>
      <p>Wallet gap vs. opportunity score, colored by refinancing flag.</p>
      <ResponsiveContainer width="100%" height={500}>
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid stroke="#e1e0d9" />
          <XAxis
            type="number"
            dataKey="wallet_gap_zar"
            name="Wallet Gap (ZAR)"
            stroke="#898781"
          />
          <YAxis
            type="number"
            dataKey="opportunity_score"
            name="Opportunity Score"
            stroke="#898781"
          />
          <Tooltip
            cursor={{ strokeDasharray: '3 3' }}
            content={<HeatmapTooltip />}
          />
          <Legend />
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
    </>
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

  return (
    <>
      <button type="button" onClick={onBack}>
        &larr; Back
      </button>

      {loading && <p>Loading client...</p>}
      {error && <p>Failed to load client: {error}</p>}

      {client && (
        <>
          <h1>
            {client.entity_name} ({client.entity_id})
          </h1>
          <table>
            <tbody>
              <tr>
                <th>Sector</th>
                <td>{client.sector}</td>
              </tr>
              <tr>
                <th>Estimated Total Wallet (ZAR)</th>
                <td>{client.estimated_total_wallet_zar}</td>
              </tr>
              <tr>
                <th>Synthetic Bank Share (%)</th>
                <td>{client.syn_bank_share_pct}</td>
              </tr>
              <tr>
                <th>Wallet Gap (ZAR)</th>
                <td>{client.wallet_gap_zar}</td>
              </tr>
              <tr>
                <th>Opportunity Score</th>
                <td>{client.opportunity_score}</td>
              </tr>
              <tr>
                <th>Txn Banking (%)</th>
                <td>{client.txn_banking_pct}</td>
              </tr>
              <tr>
                <th>Cross Border (%)</th>
                <td>{client.cross_border_pct}</td>
              </tr>
              <tr>
                <th>Trade Finance (%)</th>
                <td>{client.trade_finance_pct}</td>
              </tr>
              <tr>
                <th>Lending / IB (%)</th>
                <td>{client.lending_ib_pct}</td>
              </tr>
              <tr>
                <th>Refinancing Flag</th>
                <td>{String(client.refinancing_flag)}</td>
              </tr>
              <tr>
                <th>Refinancing Window (days)</th>
                <td>{client.refinancing_window_days ?? 'N/A'}</td>
              </tr>
              <tr>
                <th>Import Mismatch Flag</th>
                <td>{String(client.import_mismatch_flag)}</td>
              </tr>
            </tbody>
          </table>
        </>
      )}
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

  if (loading) return <p>Loading clients...</p>
  if (error) return <p>Failed to load clients: {error}</p>

  return (
    <>
      {view !== 'detail' && <Nav view={view} onNavigate={handleNavigate} />}

      {view === 'table' && (
        <ClientTable clients={clients} onSelectClient={handleSelectClient} />
      )}

      {view === 'heatmap' && (
        <OpportunityHeatmap
          clients={clients}
          onSelectClient={handleSelectClient}
        />
      )}

      {view === 'detail' && (
        <ClientDetail
          entityId={selectedEntityId}
          onBack={() => setView(previousView)}
        />
      )}
    </>
  )
}

export default App
