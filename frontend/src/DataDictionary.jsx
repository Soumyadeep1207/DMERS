import React, { useMemo, useState } from 'react';

const DOWNLOADS = [
  ['/data/schema.csv', 'dmers-schema-dictionary.csv', 'Schema dictionary (CSV)', 'One row per column: type, keys, constraints, meaning, live statistics, masked sample.'],
  ['/data/relationships.csv', 'dmers-relationships.csv', 'Relationships (CSV)', 'Every foreign key with cardinality, optionality and a live orphan check.'],
  ['/data/constraints.csv', 'dmers-constraints.csv', 'Constraints (CSV)', 'Primary keys, unique, foreign keys, CHECK rules, NOT NULL and indexes.'],
  ['/data/bundle.zip', 'dmers-database-export.zip', 'Full export (ZIP)', 'All of the above plus every table’s rows, a README and SHA-256 checksums.'],
];
const SENSITIVITY_CLASS = { SECRET: 'severe', PERSONAL: 'moderate', OPERATIONAL: 'low' };

/** On-screen rendering of the same data dictionary that the CSV downloads contain. */
export default function DataDictionary({ download, fetchJson }) {
  const [schema, setSchema] = useState(null);
  const [notice, setNotice] = useState('Load the live schema to review every table, column, key and constraint, or download it as CSV.');
  const [busy, setBusy] = useState(false);
  const [table, setTable] = useState('all');
  const [view, setView] = useState('columns');

  const load = async () => {
    setBusy(true);
    try { const data = await fetchJson('/data/schema'); setSchema(data); setNotice(`Live schema read from ${data.engine}: ${data.dictionary.length} columns in ${new Set(data.dictionary.map(row => row.table)).size} tables.`); }
    catch (error) { setNotice(error.message); }
    finally { setBusy(false); }
  };
  const save = async ([path, name]) => {
    try { const saved = await download(path, name); setNotice(`Downloaded ${saved}. Password hashes are omitted and e-mail addresses are masked.`); }
    catch (error) { setNotice(error.message); }
  };
  const tables = useMemo(() => [...new Set((schema?.dictionary || []).map(row => row.table))], [schema]);
  const columns = (schema?.dictionary || []).filter(row => table === 'all' || row.table === table);
  const links = (schema?.relationships || []).filter(row => table === 'all' || row.child_table === table || row.parent_table === table);
  const rules = (schema?.constraints || []).filter(row => table === 'all' || row.table === table);
  const purposes = Object.fromEntries((schema?.dictionary || []).map(row => [row.table, row.table_purpose]));

  return <section className="dm-panel dm-dictionary" aria-label="Schema dictionary">
    <header className="dm-panel-head"><p className="dm-eyebrow">Schema documentation</p><h2>Database schema dictionary</h2><p className="dm-muted">A self-documenting export built from the live catalogue, so it always matches the database that is running.</p></header>
    <div className="dm-download-grid">{DOWNLOADS.map(item => <button key={item[0]} className="dm-download" onClick={() => save(item)}><b>{item[2]}</b><small>{item[3]}</small></button>)}</div>
    <div className="dm-row"><button className="dm-primary" onClick={load} disabled={busy}>{busy ? 'Reading catalogue…' : schema ? 'Refresh schema' : 'Show schema on screen'}</button>{schema && <><label className="dm-inline">Table<select value={table} onChange={e => setTable(e.target.value)}><option value="all">All tables</option>{tables.map(name => <option key={name}>{name}</option>)}</select></label><div className="dm-seg" role="tablist">{[['columns', 'Columns'], ['relationships', 'Relationships'], ['constraints', 'Constraints']].map(([id, label]) => <button key={id} role="tab" aria-selected={view === id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>)}</div></>}</div>
    <p className="dm-status">● {notice}</p>
    {schema && table !== 'all' && <p className="dm-callout"><b>{table}</b> — {purposes[table]}</p>}
    {schema && view === 'columns' && <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr><th>Table</th><th>#</th><th>Column</th><th>Type</th><th>Null</th><th>Keys</th><th>References</th><th>Rule</th><th>Rows</th><th>Nulls</th><th>Distinct</th><th>Sample</th><th>Sensitivity</th></tr></thead><tbody>{columns.map(row => <tr key={`${row.table}.${row.column}`} title={row.business_meaning}><td>{row.table}</td><td>{row.ordinal}</td><td><b>{row.column}</b>{row.business_meaning && <small className="dm-cell-note">{row.business_meaning}</small>}</td><td><code>{row.data_type}</code></td><td>{row.nullable}</td><td>{row.keys && row.keys.split(' ').map(key => <span key={key} className={`dm-key ${key.toLowerCase()}`}>{key}</span>)}</td><td>{row.references}{row.on_delete ? <small className="dm-cell-note">on delete {row.on_delete}</small> : null}</td><td className="dm-rule">{row.check_constraint}</td><td>{row.row_count}</td><td>{row.null_count}</td><td>{row.distinct_values}</td><td className="dm-sample">{row.sample_value}</td><td><span className={`dm-pill ${SENSITIVITY_CLASS[row.sensitivity]}`}>{row.sensitivity}</span></td></tr>)}</tbody></table></div>}
    {schema && view === 'relationships' && <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr><th>Child</th><th>Parent</th><th>Cardinality</th><th>Participation</th><th>On delete</th><th>Linked rows</th><th>Orphans</th><th>Integrity</th></tr></thead><tbody>{links.map(row => <tr key={`${row.child_table}.${row.child_column}`}><td><b>{row.child_table}</b>.{row.child_column}</td><td><b>{row.parent_table}</b>.{row.parent_column}</td><td>{row.cardinality}</td><td>{row.participation}</td><td>{row.on_delete}</td><td>{row.linked_rows}</td><td>{row.orphan_rows}</td><td><span className={`dm-pill ${row.integrity === 'OK' ? 'low' : 'severe'}`}>{row.integrity}</span></td></tr>)}</tbody></table></div>}
    {schema && view === 'constraints' && <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr><th>Table</th><th>Type</th><th>Columns</th><th>Rule</th></tr></thead><tbody>{rules.map((row, index) => <tr key={index}><td>{row.table}</td><td><span className="dm-key">{row.type}</span></td><td>{row.columns}</td><td className="dm-rule">{row.rule}</td></tr>)}</tbody></table></div>}
  </section>;
}
