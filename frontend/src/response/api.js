import { pushActivity } from './trace.js';

/** A tiny observable list of database activity, filled by every response-model call. */
const listeners = new Set();
let activity = [];
let sequence = 0;

export const getActivity = () => activity;
export const subscribeActivity = listener => { listeners.add(listener); return () => listeners.delete(listener); };
export const clearActivity = () => { activity = []; listeners.forEach(l => l()); };

export function record(entry) {
  activity = pushActivity(activity, { id: ++sequence, at: new Date().toISOString(), ...entry });
  listeners.forEach(l => l());
}

/**
 * Call the API. ``token`` overrides the signed-in user (the guided demo acts as several people).
 * Every response that carries a ``db_trace`` is recorded for the Database activity panel, whether it
 * succeeded or was refused. Returns {status, ok, body}; it never throws for HTTP errors.
 */
export async function call(method, path, body, { token, label, person } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const bearer = token ?? localStorage.getItem('dmers-token');
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let response, data = {};
  try {
    response = await fetch(path, { method, headers, body: body == null ? undefined : JSON.stringify(body) });
    const text = await response.text();
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    data = { error: response ? 'The server sent an unreadable response.' : 'The server could not be reached.' };
  }
  const status = response?.status ?? 0;
  if (data.db_trace) record({ label: label || data.db_trace.operation, person, method, path, status, ok: status < 400, message: data.error || '', trace: data.db_trace });
  return { status, ok: status >= 200 && status < 300, body: data };
}

export const get = (path, options) => call('GET', path, undefined, options);
export const post = (path, body, options) => call('POST', path, body, options);
export const patch = (path, body, options) => call('PATCH', path, body, options);
export const del = (path, options) => call('DELETE', path, undefined, options);
