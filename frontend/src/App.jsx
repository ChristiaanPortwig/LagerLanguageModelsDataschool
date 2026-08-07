import { useEffect, useState } from 'react'

const API_BASE = 'http://localhost:4000/api/clients'

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
        &larr; Back to table
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
  const [selectedEntityId, setSelectedEntityId] = useState(null)

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

  if (loading) return <p>Loading clients...</p>
  if (error) return <p>Failed to load clients: {error}</p>

  if (selectedEntityId) {
    return (
      <ClientDetail
        entityId={selectedEntityId}
        onBack={() => setSelectedEntityId(null)}
      />
    )
  }

  return <ClientTable clients={clients} onSelectClient={setSelectedEntityId} />
}

export default App
