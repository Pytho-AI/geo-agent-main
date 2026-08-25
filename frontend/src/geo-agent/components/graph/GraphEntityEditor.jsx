// Entity INSPECTOR over the graph (EntityPanel evolution — design §7).
// READ-ONLY since the S17 cutover (2026-07-28): the legacy node/edge/
// holdings CRUD routes are gone — every record write goes through the
// world surface's general verbs, chained to captured L0, and an
// analyst edit citing no source is not a record write. The one
// writable tab is FIELDS: extensible display fields (working layer —
// description, never record data).
import { useEffect, useMemo, useState } from 'react'
import { graphApi } from '../../utils/graphApi'

const S = {
  wrap: { borderTop: '1px solid #374151', maxHeight: '55%', overflowY: 'auto',
    background: '#0f172a', padding: 10, fontSize: 12.5 },
  tabs: { display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' },
  tab: (on) => ({ padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
    background: on ? '#2563eb' : '#1f2937', color: '#e5e7eb',
    border: '1px solid #374151', fontSize: 12 }),
  lbl: { display: 'block', color: '#9ca3af', marginTop: 6, marginBottom: 2 },
  in: { width: '100%', background: '#111827', color: '#e5e7eb',
    border: '1px solid #374151', borderRadius: 4, padding: '3px 6px' },
  btn: { background: '#1f2937', color: '#e5e7eb', border: '1px solid #4b5563',
    borderRadius: 4, padding: '3px 8px', cursor: 'pointer', fontSize: 12 },
  row: { display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 },
  ro: { color: '#e5e7eb' },
}

function Field({ label, children }) {
  return <div><span style={S.lbl}>{label}</span><span style={S.ro}>{children}</span></div>
}

export function GraphEntityEditor({ mapId, userId, bulk, entity, onChanged, onClose }) {
  const [tab, setTab] = useState('identity')
  const [error, setError] = useState(null)

  useEffect(() => { setTab('identity'); setError(null) }, [entity?.id])

  const typeRow = useMemo(() => (bulk.entity_types || [])
    .find(t => t.type_key === entity.entity_type), [bulk, entity])
  const isFixed = !!typeRow?.is_fixed
  const holdings = useMemo(() => (bulk.holdings || [])
    .filter(h => h.node_id === entity.id), [bulk, entity])
  const fields = useMemo(() => (bulk.node_fields || [])
    .filter(f => f.node_id === entity.id), [bulk, entity])
  const edges = useMemo(() => (bulk.edges || [])
    .filter(e => e.from_id === entity.id || e.to_id === entity.id), [bulk, entity])
  const rtypes = Object.fromEntries((bulk.relationship_types || [])
    .map(t => [t.type_key, t]))
  const nodeName = (id) => (bulk.entities.find(e => e.id === id) || {}).name || id

  const TABS = ['identity', 'fields', 'equipment', 'relationships', 'status']
  return (
    <div style={S.wrap}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ flex: 1 }}>{entity.name}</strong>
        <span style={{ color: '#6b7280', fontSize: 11 }}
              title={'The record browser is read-only: record corrections '
                + 'go through the world surface (assert/update/retract), '
                + 'every write chained to its stating source.'}>
          record view
        </span>
        <button style={S.btn} onClick={onClose}>✕</button>
      </div>
      {error && <div style={{ color: '#fca5a5' }}>{error}</div>}
      <div style={S.tabs}>
        {TABS.map(t => (
          <span key={t} style={S.tab(tab === t)} onClick={() => setTab(t)}>{t}</span>
        ))}
      </div>

      {tab === 'identity' && (
        <div>
          <Field label="Entity type (registry)">{typeRow?.label || entity.entity_type}</Field>
          <Field label="Name">{entity.name}</Field>
          <Field label="Affiliation">{entity.affiliation || '—'}</Field>
          {!isFixed && (
            <>
              <Field label="Echelon">{entity.echelon || '—'}</Field>
              <Field label="Unit type">{entity.unit_type || '—'}</Field>
            </>
          )}
          <Field label="Command parent">
            {entity.organic_parent_id ? nodeName(entity.organic_parent_id) : '— none (root) —'}
          </Field>
          <Field label="Significance">{entity.significance || '—'}</Field>
          <Field label="Significance rationale">{entity.significance_note || '—'}</Field>
          <Field label="Notes">{entity.notes || '—'}</Field>
        </div>
      )}

      {tab === 'fields' && (
        <div>
          {fields.map(f => (
            <div key={f.field_key} style={S.row}>
              <span style={{ width: 110, color: '#9ca3af' }}>{f.field_key}</span>
              <input style={{ ...S.in, flex: 1 }} defaultValue={f.value}
                     onBlur={async (e) => {
                       if (e.target.value !== f.value) {
                         try { await graphApi.putNodeField(entity.id, f.field_key, e.target.value, userId); onChanged() }
                         catch (err) { setError(String(err.message || err)) }
                       }
                     }} />
              <button style={S.btn} onClick={async () => {
                try { await graphApi.deleteNodeField(entity.id, f.field_key); onChanged() }
                catch (err) { setError(String(err.message || err)) }
              }}>✕</button>
            </div>
          ))}
          <AddField bulk={bulk} entity={entity} userId={userId}
                    onChanged={onChanged} onError={setError} />
        </div>
      )}

      {tab === 'equipment' && (
        <div>
          {holdings.length === 0 && <div style={{ color: '#6b7280' }}>None recorded</div>}
          {holdings.map(h => (
            <div key={h.id} style={S.row}>
              <span style={{ flex: 1 }}>
                {h.catalog?.name || h.nomenclature_raw || h.weg_id}
                {!h.weg_id && <em style={{ color: '#f59e0b' }}> (unresolved)</em>}
              </span>
              <span style={S.ro}>{h.count_current ?? '—'}</span>
              <span style={{ color: '#6b7280' }}>/ {h.count_authorized ?? '—'}</span>
            </div>
          ))}
        </div>
      )}

      {tab === 'relationships' && (
        <div>
          {edges.length === 0 && <div style={{ color: '#6b7280' }}>None recorded</div>}
          {edges.map(e => {
            const rt = rtypes[e.relationship_type] || {}
            const outgoing = e.from_id === entity.id
            const other = outgoing ? e.to_id : e.from_id
            return (
              <div key={e.id} style={S.row}>
                <span style={{ flex: 1 }}>
                  {outgoing ? (rt.label || e.relationship_type)
                            : (rt.inverse_label || e.relationship_type)}{' '}
                  <strong>{nodeName(other)}</strong>
                  {e.effective_to && <em style={{ color: '#6b7280' }}> (closed)</em>}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {tab === 'status' && (
        <div>
          {!isFixed && (
            <>
              <Field label="Personnel current / authorized">
                {`${entity.personnel_current ?? '—'} / ${entity.personnel_authorized ?? '—'}`}
              </Field>
              <Field label="Casualties (killed / wounded / captured)">
                {`${entity.personnel_killed ?? 0} / ${entity.personnel_wounded ?? 0} / ${entity.personnel_captured ?? 0}`}
              </Field>
            </>
          )}
          <Field label="Combat effectiveness (assessment)">
            {entity.combat_effectiveness || '—'}
          </Field>
          <Field label="Assessment basis">{entity.assessment_basis || '—'}</Field>
          <Field label={isFixed ? 'Operational status note' : 'Posture (record)'}>
            {entity.posture || '—'}
          </Field>
          <Field label="Current activity">{entity.current_activity || '—'}</Field>
        </div>
      )}
    </div>
  )
}

function AddField({ bulk, entity, userId, onChanged, onError }) {
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const defs = bulk.field_defs || []
  return (
    <div style={S.row}>
      <select style={{ ...S.in, width: 130 }} value={key}
              onChange={e => setKey(e.target.value)}>
        <option value="">+ field…</option>
        {defs.map(d => <option key={d.field_key} value={d.field_key}>{d.label}</option>)}
      </select>
      <input style={{ ...S.in, flex: 1 }} placeholder="value" value={value}
             onChange={e => setValue(e.target.value)} />
      <button style={S.btn} disabled={!key || !value} onClick={async () => {
        try {
          await graphApi.putNodeField(entity.id, key, value, userId)
          setKey(''); setValue(''); onChanged()
        } catch (err) { onError(String(err.message || err)) }
      }}>Add</button>
    </div>
  )
}
