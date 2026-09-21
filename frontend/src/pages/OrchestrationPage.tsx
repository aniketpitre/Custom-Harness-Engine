import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function OrchestrationPage() {
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);

  useEffect(() => {
    api.get('/orchestration/workflows').then(setWorkflows).catch(() => setWorkflows([]));
  }, []);

  const loadDetail = (id: string) => {
    api.get(`/orchestration/workflows/${id}`).then(setSelected).catch(console.error);
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Orchestration</h2>
      <p className="text-xs text-slate-500">Multi-agent workflow visualization — unique to Harness Engine (no Hermes equivalent).</p>

      {workflows.length === 0 ? (
        <div className="rounded border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-500">
          No workflows recorded. Orchestration data will appear when multi-agent workflows run.
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {workflows.map((w: any) => (
            <button
              key={w.id}
              onClick={() => loadDetail(w.id)}
              className="rounded border border-slate-800 bg-slate-900/50 p-4 text-left hover:border-indigo-600 transition-colors"
            >
              <div className="font-medium">{w.id}</div>
              <div className="text-xs text-slate-400 mt-1">Phases: {w.total_phases ?? '?'}</div>
              <div className="text-xs text-slate-500">{w.status ?? 'unknown'}</div>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="rounded border border-indigo-800 bg-slate-900/50 p-4 space-y-3">
          <h3 className="font-semibold text-lg">Workflow Detail: {selected.id}</h3>
          <div className="space-y-2">
            {(selected.phases ?? []).map((phase: any, i: number) => (
              <div key={i} className="flex items-center gap-3">
                <div className={`h-3 w-3 rounded-full ${
                  phase.status === 'completed' ? 'bg-green-500' :
                  phase.status === 'running' ? 'bg-blue-500 animate-pulse' :
                  'bg-slate-600'
                }`} />
                <div className="text-sm">Phase {i}: <span className="text-slate-400">{phase.status}</span></div>
              </div>
            ))}
          </div>
          {selected.resumable && (
            <button className="rounded bg-indigo-600 px-4 py-1.5 text-sm">Resume Workflow</button>
          )}
        </div>
      )}
    </div>
  );
}
