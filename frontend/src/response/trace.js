/** Pure helpers that turn a backend ``db_trace`` into the five questions the course guidelines ask. */

export const FIVE_QUESTIONS = [
  'What operation is performed?',
  'Which tables are involved?',
  'Which SQL / PL-SQL component runs?',
  'How is the database affected?',
  'What result is produced?',
];

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

export function rowSummary(rowChanges = {}) {
  return Object.entries(rowChanges).map(([table, change]) => `${table}: ${Object.entries(change).map(([kind, n]) => `${n} ${kind}`).join(', ')}`);
}

const show = value => (value === null || value === undefined ? 'none' : typeof value === 'object' ? Object.entries(value).map(([k, v]) => `${k} ${v === null ? 'none' : v}`).join(', ') : String(value));

export function effectLines(effects = []) {
  return effects.map(effect => (effect.unchanged
    ? `${effect.label}: unchanged (${show(effect.before)}) - the transaction was rolled back`
    : `${effect.label}: ${show(effect.before)} → ${show(effect.after)}`));
}

/** Answers for one operation. ``message`` is the HTTP result text (success summary or the database's refusal). */
export function describeTrace(trace, message = '') {
  if (!trace) return null;
  const failed = trace.rolled_back || trace.outcome === 'rolled_back';
  const components = trace.components?.length ? trace.components : ['the statement itself (constraints only)'];
  const changes = rowSummary(trace.row_changes);
  const effects = effectLines(trace.effects);
  const how = failed
    ? ['Nothing was changed: the whole transaction was rolled back.', ...effects]
    : [changes.length ? `${plural(trace.rows_affected, 'row')} changed: ${changes.join('; ')}` : 'No rows changed (read or check only).', ...effects];
  const result = failed
    ? `Refused by the database: ${message || trace.failure?.message || 'a rule was violated'}${trace.failure?.constraint ? ` (constraint ${trace.failure.constraint})` : ''}`
    : `Committed in ${trace.duration_ms} ms${trace.notices?.length ? `. Database notices: ${trace.notices.join(' | ')}` : ''}${message ? `. ${message}` : ''}`;
  return {
    outcome: failed ? 'ROLLED BACK' : 'COMMITTED',
    answers: [
      { question: FIVE_QUESTIONS[0], answer: [trace.operation] },
      { question: FIVE_QUESTIONS[1], answer: trace.tables_touched?.length ? trace.tables_touched : ['none'] },
      { question: FIVE_QUESTIONS[2], answer: components },
      { question: FIVE_QUESTIONS[3], answer: how },
      { question: FIVE_QUESTIONS[4], answer: [result] },
    ],
    statements: trace.statements || [],
    statementStatus: trace.statement_status || [],
    constraints: trace.constraints_checked || [],
    details: trace.component_details || [],
  };
}

/** Newest-first list with a fixed capacity, for the Database activity panel. */
export function pushActivity(list, entry, capacity = 30) {
  return [entry, ...list].slice(0, capacity);
}
