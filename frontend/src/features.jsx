import { Fragment, useEffect, useMemo, useState } from 'react'
import { apiRequest } from './api'
import { formatFieldName } from './featureFormat'
import { formatZarAbbreviated, formatZarFull } from './format'

export function ConfidenceBadge({ level, onClick }) {
  const normalized = level || "can't estimate"
  const variant = normalized.replace(/[^a-z]+/g, '-')
  const content = `${formatFieldName(normalized)} confidence`
  if (!onClick) return <span className={`badge badge-confidence badge-${variant}`}>{content}</span>
  return (
    <button
      type="button"
      className={`badge badge-confidence badge-${variant}`}
      onClick={onClick}
      title="See why this confidence rating was assigned"
    >
      {content}
    </button>
  )
}

function StatusMessage({ error, success }) {
  if (error) return <p className="form-message state-message-error">{error}</p>
  if (success) return <p className="form-message form-message-success">{success}</p>
  return null
}

export function ManualDataForm({ entityId, fields, initialField, onSaved, onCancel }) {
  const uniqueFields = useMemo(() => [...new Set(fields || [])].sort(), [fields])
  const [field, setField] = useState(initialField || uniqueFields[0] || '')
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (initialField) setField(initialField)
  }, [initialField])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError(null)
    if (!field || value === '') {
      setError('Choose a field and enter a value.')
      return
    }
    setSaving(true)
    try {
      const updated = await apiRequest(`/clients/${entityId}/missing-data`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: { [field]: Number(value) } }),
      })
      setValue('')
      onSaved?.(updated)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <label>
        Missing field
        <select value={field} onChange={(event) => setField(event.target.value)}>
          {uniqueFields.map((item) => (
            <option value={item} key={item}>{formatFieldName(item)}</option>
          ))}
        </select>
      </label>
      <label>
        Value (ZAR or source unit)
        <input
          type="number"
          min="0"
          step="any"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          required
        />
      </label>
      <div className="form-actions">
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? 'Saving…' : 'Save data'}
        </button>
        {onCancel && <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>}
      </div>
      <StatusMessage error={error} />
    </form>
  )
}

export function DocumentUploadForm({ entityId, initialType = 'annual_report', onUploaded, onCancel }) {
  const [documentType, setDocumentType] = useState(initialType)
  const [year, setYear] = useState(new Date().getFullYear())
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!file) return
    setUploading(true)
    setError(null)
    setSuccess(null)
    const query = new URLSearchParams({ document_type: documentType, year: String(year) })
    const formData = new FormData()
    formData.append('file', file)
    try {
      const result = await apiRequest(`/clients/${entityId}/documents?${query}`, {
        method: 'POST',
        body: formData,
      })
      setSuccess('PDF accepted. The pipeline will process it in the background.')
      onUploaded?.(result)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <label>
        Document type
        <select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
          <option value="annual_report">Annual report</option>
          <option value="financial_statements">Financial statements</option>
          <option value="interim_results">Interim results</option>
          <option value="results_presentation">Results presentation</option>
          <option value="SENS">SENS</option>
        </select>
      </label>
      <label>
        Year
        <input
          type="number"
          min="2000"
          max="2100"
          value={year}
          onChange={(event) => setYear(event.target.value)}
          required
        />
      </label>
      <label className="form-wide">
        PDF
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={(event) => setFile(event.target.files?.[0] || null)}
          required
        />
      </label>
      <div className="form-actions">
        <button type="submit" className="btn-primary" disabled={uploading}>
          {uploading ? 'Uploading…' : 'Upload PDF'}
        </button>
        {onCancel && <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>}
      </div>
      <StatusMessage error={error} success={success} />
    </form>
  )
}

export function ConfidenceDetails({ entityId, calculation, initialPillar, onDataSaved }) {
  const confidence = calculation?.confidence || {}
  const pillarKeys = Object.keys(confidence)
  const [selectedPillar, setSelectedPillar] = useState(initialPillar || pillarKeys[0])
  const [editingField, setEditingField] = useState(null)

  useEffect(() => {
    if (initialPillar) setSelectedPillar(initialPillar)
  }, [initialPillar])

  if (!pillarKeys.length) return <p className="state-message state-message-inline">No confidence detail is available.</p>
  const selected = confidence[selectedPillar] || {}

  return (
    <>
      <div className="confidence-tabs">
        {pillarKeys.map((pillar) => (
          <ConfidenceBadge
            key={pillar}
            level={confidence[pillar]?.level}
            onClick={() => setSelectedPillar(pillar)}
          />
        ))}
      </div>
      <h3 className="subsection-title">{formatFieldName(selectedPillar)}</h3>
      {selected.reasons?.length ? (
        <div className="reason-list">
          {selected.reasons.map((reason) => (
            <div className="reason-item" key={`${reason.product}-${reason.tier}`}>
              <div className="reason-heading">
                <strong>{formatFieldName(reason.product)}</strong>
                <span>{reason.tier ? `Tier ${reason.tier} · ${reason.status}` : reason.status}</span>
              </div>
              <div className="stat-label">Missing inputs</div>
              <div className="field-list">
                {reason.missing_fields.map((missingField) => (
                  <button
                    type="button"
                    className="field-chip"
                    key={missingField}
                    onClick={() => setEditingField(missingField)}
                  >
                    {formatFieldName(missingField)} +
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : <p className="state-message state-message-inline">All preferred inputs are available for this pillar.</p>}
      {editingField && (
        <div className="nested-form">
          <ManualDataForm
            entityId={entityId}
            fields={calculation?.missing_data?.fields || [editingField]}
            initialField={editingField}
            onCancel={() => setEditingField(null)}
            onSaved={(updated) => {
              setEditingField(null)
              onDataSaved?.(updated)
            }}
          />
        </div>
      )}
    </>
  )
}

export function WalletCalculation({ calculation }) {
  const products = Object.entries(calculation?.products || {})
  const pillars = Object.entries(calculation?.pillars || {})
  if (!products.length) return <p className="state-message state-message-inline">No wallet calculation is available.</p>
  return (
    <>
      <div className="formula-summary">
        {pillars.map(([pillar, detail]) => (
          <div key={pillar}>
            <div className="stat-label">{formatFieldName(pillar)}</div>
            <code>{detail.formula}</code>
          </div>
        ))}
        {calculation.total && (
          <div>
            <div className="stat-label">Total wallet</div>
            <code>{calculation.total.formula}</code>
          </div>
        )}
      </div>
      <div className="table-scroll">
        <table className="data-table formula-table">
          <thead><tr><th>Product</th><th>Tier</th><th>Formula</th><th>Inputs</th><th className="numeric">Result</th></tr></thead>
          <tbody>
            {products.map(([product, detail]) => (
              <tr key={product}>
                <td className="entity-name">{formatFieldName(product)}</td>
                <td>{detail.tier ? <span className="badge badge-neutral">Tier {detail.tier}</span> : 'Unavailable'}</td>
                <td><code>{detail.formula || 'Missing required inputs'}</code></td>
                <td>{Object.keys(detail.inputs || {}).map(formatFieldName).join(', ') || '—'}</td>
                <td className="numeric" title={detail.value == null ? '' : formatZarFull(detail.value)}>
                  {detail.value == null ? '—' : formatZarAbbreviated(detail.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function PipelineControls() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  const loadStatus = () => apiRequest('/pipeline/status').then(setStatus).catch((requestError) => setError(requestError.message))
  useEffect(() => { loadStatus() }, [])
  useEffect(() => {
    if (!status?.running) return undefined
    const timer = window.setInterval(loadStatus, 3000)
    return () => window.clearInterval(timer)
  }, [status?.running])

  const run = async (scope) => {
    setError(null)
    try {
      await apiRequest('/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope }),
      })
      setStatus({ ...status, running: true, state: 'running', last_scope: scope })
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  return (
    <section className="panel detail-section">
      <h2>Data Pipeline</h2>
      <div className="toolbar">
        <span className={`badge ${status?.running ? 'badge-warning' : 'badge-neutral'}`}>{status?.running ? 'Running' : 'Idle'}</span>
        <button className="btn-secondary" type="button" disabled={status?.running} onClick={() => run('sens')}>Refresh SENS</button>
        <button className="btn-secondary" type="button" disabled={status?.running} onClick={() => run('all')}>Refresh all sources</button>
      </div>
      {status?.last_completed_at && <p className="view-subtitle">Last completed {new Date(status.last_completed_at).toLocaleString('en-ZA')}.</p>}
      {status?.sens_scoring?.state === 'running' && (
        <p className="view-subtitle">
          Gemini is scoring {status.sens_scoring.rows_submitted} SENS row{status.sens_scoring.rows_submitted === 1 ? '' : 's'}…
        </p>
      )}
      {status?.sens_scoring?.state === 'complete' && status.sens_scoring.rows_submitted > 0 && (
        <p className="view-subtitle">
          Gemini completed {status.sens_scoring.rows_submitted} SENS score{status.sens_scoring.rows_submitted === 1 ? '' : 's'}.
        </p>
      )}
      <StatusMessage error={error || status?.error} />
    </section>
  )
}

export function DataQualityPage({ clients, onClientsChanged }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(null)
  const [editingWallet, setEditingWallet] = useState(null)

  const load = () => apiRequest('/missing-data').then(setData).catch((requestError) => setError(requestError.message))
  useEffect(() => { load() }, [])
  const entityForCompany = (company) => clients.find((client) => client.entity_name === company)?.entity_id

  if (error) return <p className="state-message">Failed to load data gaps: {error}</p>
  if (!data) return <p className="state-message">Loading data gaps...</p>
  return (
    <>
      <h2 className="view-heading">Data Gaps</h2>
      <p className="view-subtitle">Missing documents and financial inputs that reduce calculation confidence. SENS data is processed automatically by Gemini.</p>
      <PipelineControls />
      <section className="panel detail-section">
        <h2>Missing PDFs</h2>
        {!data.documents.length ? <p>No missing PDFs are currently flagged.</p> : (
          <div className="table-scroll"><table className="data-table"><thead><tr><th>Company</th><th>Document</th><th>Reason</th><th>Action</th></tr></thead><tbody>
            {data.documents.map((document) => {
              const entityId = entityForCompany(document.company)
              const key = `${document.company}-${document.document_type}`
              return <tr key={key}><td className="entity-name">{document.company}</td><td>{formatFieldName(document.document_type)}</td><td>{document.reason}</td><td><button type="button" className="text-button" disabled={!entityId} onClick={() => setUploading(uploading === key ? null : key)}>Upload PDF</button></td></tr>
            })}
          </tbody></table></div>
        )}
        {uploading && (() => {
          const [document] = data.documents.filter((item) => `${item.company}-${item.document_type}` === uploading)
          return document ? <div className="nested-form"><h3 className="subsection-title">Upload for {document.company}</h3><DocumentUploadForm entityId={entityForCompany(document.company)} initialType={document.document_type} onCancel={() => setUploading(null)} onUploaded={() => { setUploading(null); load() }} /></div> : null
        })()}
      </section>
      <section className="panel detail-section">
        <h2>Missing Wallet Inputs</h2>
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Company</th><th className="numeric">Missing fields</th><th>Action</th></tr></thead><tbody>
          {data.wallet_fields.map((record) => (
            <Fragment key={record.entity_id}>
              <tr><td className="entity-name">{record.company}</td><td className="numeric">{record.fields.length}</td><td><button type="button" className="text-button" onClick={() => setEditingWallet(editingWallet === record.entity_id ? null : record.entity_id)}>Add data</button></td></tr>
              {editingWallet === record.entity_id && (
                <tr className="inline-editor-row">
                  <td className="inline-editor-cell" colSpan="3">
                    <div className="nested-form"><h3 className="subsection-title">Add data for {record.company}</h3><ManualDataForm entityId={record.entity_id} fields={record.fields} onCancel={() => setEditingWallet(null)} onSaved={() => { setEditingWallet(null); load(); onClientsChanged?.() }} /></div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody></table></div>
      </section>
    </>
  )
}

export function FormulasPage() {
  const [data, setData] = useState(null)
  const [company, setCompany] = useState('')
  const [error, setError] = useState(null)
  useEffect(() => { apiRequest('/formulas').then((result) => { setData(result); setCompany(Object.keys(result.wallet?.formulas || {})[0] || '') }).catch((requestError) => setError(requestError.message)) }, [])
  if (error) return <p className="state-message">Failed to load formulas: {error}</p>
  if (!data) return <p className="state-message">Loading formulas...</p>
  const companies = Object.keys(data.wallet?.formulas || {})
  return (
    <>
      <h2 className="view-heading">Calculation Formulas</h2>
      <p className="view-subtitle">Auditable opportunity and wallet formulas, including the tier selected for every product.</p>
      <section className="panel detail-section"><h2>Opportunity Score</h2><div className="definition-grid"><div><div className="stat-label">Pillar score</div><code>{data.opportunity_pillar}</code></div><div><div className="stat-label">Total score</div><code>{data.opportunity_total}</code></div><div><div className="stat-label">SENS decay ({data.sens_half_life_days} day half-life)</div><code>{data.sens_decay}</code></div></div></section>
      <section className="panel detail-section">
        <div className="section-title-row"><h2>Wallet Size</h2><label className="compact-control">Company<select value={company} onChange={(event) => setCompany(event.target.value)}>{companies.map((name) => <option key={name}>{name}</option>)}</select></label></div>
        <WalletCalculation calculation={data.wallet?.formulas?.[company]} />
      </section>
    </>
  )
}

export function SettingsPage({ onClientsChanged }) {
  const [settings, setSettings] = useState(null)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => { apiRequest('/formulas').then((data) => setSettings({ ...data.score_weights, sens_half_life_days: data.sens_half_life_days })).catch((requestError) => setError(requestError.message)) }, [])
  if (!settings) return <p className="state-message">{error ? `Failed to load settings: ${error}` : 'Loading settings...'}</p>
  const update = (key, value) => setSettings({ ...settings, [key]: value })
  const total = Number(settings.gap_weight) + Number(settings.sens_weight) + Number(settings.relationship_weight)
  const submit = async (event) => {
    event.preventDefault(); setSaving(true); setError(null); setSuccess(null)
    try {
      const payload = Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, Number(value)]))
      const result = await apiRequest('/settings/scoring', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      setSettings({ ...result.score_weights, sens_half_life_days: result.sens_half_life_days })
      setSuccess(`Settings saved and scores recalculated for ${result.client_count} clients.`)
      onClientsChanged?.()
    } catch (requestError) { setError(requestError.message) } finally { setSaving(false) }
  }
  return (
    <>
      <h2 className="view-heading">Settings</h2><p className="view-subtitle">Changes are persisted and recalculate all opportunity scores.</p>
      <section className="panel detail-section"><h2>Scoring Parameters</h2><form className="settings-form" onSubmit={submit}>
        <label>Wallet gap weight<input type="number" min="0" max="1" step="0.01" value={settings.gap_weight} onChange={(event) => update('gap_weight', event.target.value)} /></label>
        <label>Opportunity / SENS weight<input type="number" min="0" max="1" step="0.01" value={settings.sens_weight} onChange={(event) => update('sens_weight', event.target.value)} /></label>
        <label>Relationship weight<input type="number" min="0" max="1" step="0.01" value={settings.relationship_weight} onChange={(event) => update('relationship_weight', event.target.value)} /></label>
        <label>SENS half-life decay (days)<input type="number" min="1" step="1" value={settings.sens_half_life_days} onChange={(event) => update('sens_half_life_days', event.target.value)} /></label>
        <div className={`weight-total ${Math.abs(total - 1) < 0.000001 ? '' : 'state-message-error'}`}>Score weights total: {total.toFixed(2)} (must equal 1.00)</div>
        <div className="form-actions"><button className="btn-primary" type="submit" disabled={saving || Math.abs(total - 1) >= 0.000001}>{saving ? 'Saving and recalculating…' : 'Save settings'}</button></div>
        <StatusMessage error={error} success={success} />
      </form></section>
    </>
  )
}
