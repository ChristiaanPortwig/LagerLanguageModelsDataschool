import { useEffect, useState } from 'react'

const API_URL = 'http://localhost:4000/api/clients'

function App() {
  const [clients, setClients] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(API_URL)
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
            <tr key={client.entity_id}>
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

export default App
