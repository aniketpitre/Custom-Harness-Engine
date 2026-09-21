import { useEffect, useState } from 'react';
import { api } from '../lib/api';

interface StatusData {
  active_runs: number;
  total_sessions: number;
  recent_sessions: any[];
  gateway_health: string;
}

export function OverviewPage() {
  const [status, setStatus] = useState<StatusData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = () => {
    api.get('/status')
      .then(setStatus)
      .catch(() => {
        // Fallback: build status from /runs
        api.get('/runs').then((runs: any[]) => {
          setStatus({
            active_runs: runs.filter((r) => r.status === 'running').length,
            total_sessions: runs.length,
            recent_sessions: runs.slice(0, 20),
            gateway_health: 'ok',
          });
        }).catch((e) => setError(e.message));
      });
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 10_000);
    return () => clearInterval(interval);
  }, []);

  if (error) return <div className="text-red-400">Error: {error}</div>;
  if (!status) return <div className="text-slate-400">Loading...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Overview</h2>

      {/* Status cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card label="Active Runs" value={status.active_runs} />
        <Card label="Total Sessions" value={status.total_sessions} />
        <Card label="Gateway" value={status.gateway_health} />
      </div>

      {/* Recent runs */}
      <div>
        <h3 className="text-lg font-semibold mb-2">Recent Runs</h3>
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left">
              <tr>
                <th className="p-2">Goal</th>
                <th className="p-2">Status</th>
                <th className="p-2">Agent</th>
                <th className="p-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {(status.recent_sessions ?? []).map((s: any) => (
                <tr key={s.id} className="border-t border-slate-800 hover:bg-slate-900/50">
                  <td className="p-2 max-w-xs truncate">{s.goal}</td>
                  <td className="p-2">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="p-2 text-slate-400">{s.agent_id}</td>
                  <td className="p-2 text-slate-500 text-xs">{s.created_at}</td>
                </tr>
              ))}
              {(!status.recent_sessions || status.recent_sessions.length === 0) && (
                <tr><td colSpan={4} className="p-4 text-center text-slate-500">No sessions yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: 'text-green-400 bg-green-400/10',
    running: 'text-blue-400 bg-blue-400/10',
    pending: 'text-yellow-400 bg-yellow-400/10',
    failure: 'text-red-400 bg-red-400/10',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? 'text-slate-400 bg-slate-400/10'}`}>
      {status}
    </span>
  );
}
