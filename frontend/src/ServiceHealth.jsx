import { useCallback, useEffect, useState } from 'react';

export function useServiceHealth() {
  const [health, setHealth] = useState({ state: 'checking', engine: null, checkedAt: null });
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    let checking = false;
    const controller = new AbortController();

    async function check() {
      if (checking) return;
      checking = true;
      try {
        const response = await fetch('/api/health', { cache: 'no-store', signal: controller.signal });
        const payload = await response.json();
        if (!active) return;
        const courseReady = !payload.review2_database?.configured || payload.review2_database?.connected;
        const engine = payload.review2_database?.connected
          ? `${payload.database?.engine || 'Database'} + Review II`
          : payload.database?.engine || null;
        setHealth({
          state: response.ok && payload.status === 'ok' && payload.database?.connected && courseReady
            ? 'healthy'
            : payload.backend === 'running' ? 'database-down' : 'backend-down',
          engine,
          checkedAt: new Date(),
        });
      } catch {
        if (active) setHealth({ state: 'backend-down', engine: null, checkedAt: new Date() });
      } finally {
        checking = false;
      }
    }

    check();
    const timer = window.setInterval(check, 15000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refreshKey]);

  const refresh = useCallback(() => setRefreshKey(value => value + 1), []);
  return { health, refresh };
}

export function ServiceHealthBadge({ health, onRefresh }) {
  const labels = {
    checking: 'Checking services',
    healthy: `${health.engine || 'Database'} connected`,
    'database-down': 'Database unavailable',
    'backend-down': 'Backend unavailable',
  };
  const checked = health.checkedAt ? `Last checked ${health.checkedAt.toLocaleTimeString()}` : 'Checking the API and database';

  return <button
    type="button"
    className={`service-health service-health-${health.state}`}
    onClick={onRefresh}
    title={`${checked}. Click to refresh.`}
    aria-label={`${labels[health.state]}. Click to refresh service status.`}
    aria-live="polite"
  >
    <span className="service-health-dot" aria-hidden="true" />
    {labels[health.state]}
  </button>;
}
