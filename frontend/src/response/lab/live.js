import { parseSse } from './labLogic.js';

/**
 * Subscribe to the server-sent event stream fed by PostgreSQL LISTEN/NOTIFY.
 * fetch() is used instead of EventSource because the request must carry the Authorization header.
 * Reconnects with a short back-off; returns a function that stops it.
 */
export function connectLive(onEvent, onState = () => {}) {
  let stopped = false;
  let controller = null;
  const run = async () => {
    let delay = 1000;
    while (!stopped) {
      controller = new AbortController();
      try {
        const token = localStorage.getItem('dmers-token');
        const response = await fetch('/api/response/stream', { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal });
        if (response.status === 403) { onState('forbidden'); return; }
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        onState('live');
        delay = 1000;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSse(buffer);
          buffer = parsed.rest;
          parsed.events.forEach(onEvent);
        }
      } catch (error) {
        if (stopped) return;
      }
      if (stopped) return;
      onState('reconnecting');
      await new Promise(resolve => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 15000);
    }
  };
  run();
  return () => { stopped = true; controller?.abort(); onState('off'); };
}
