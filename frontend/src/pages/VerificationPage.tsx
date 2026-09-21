import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function VerificationPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [filter, setFilter] = useState<'all' | 'pass' | 'fail'>('all');

  useEffect(() => {
    api.get('/runs').then(setRuns).catch(() => setRuns([]));
  }, []);

  const withVerification = runs.map((r) => {
    try {
      const receipt = JSON.parse(r.run_receipt || '{}');
      return { ...r, verification: receipt?.verification ?? null };
    } catch { return { ...r, verification: null }; }
  }).filter((r) => r.verification);

  const filtered = withVerification.filter((r) => {
    if (filter === 'pass') return r.verification?.passed;
    if (filter === 'fail') return !r.verification?.passed;
    return true;
  });

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Verification</h2>
      <p className="text-xs text-slate-500">Expected-vs-observed results across runs — unique to Harness Engine (no Hermes equivalent).</p>

      <div className="flex gap-2">
        {(['all', 'pass', 'fail'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded px-3 py-1 text-xs capitalize ${filter === f ? 'bg-indigo-600' : 'bg-slate-800 hover:bg-slate-700'}`}
          >
            {f}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="rounded border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-500">
          No verification data. Runs with verification checks will appear here.
        </div>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left">
              <tr>
                <th className="p-2">Goal</th>
                <th className="p-2">Result</th>
                <th className="p-2">Expected</th>
                <th className="p-2">Observed</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-900/50">
                  <td className="p-2 max-w-xs truncate">{r.goal}</td>
                  <td className="p-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      r.verification?.passed ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                    }`}>
                      {r.verification?.passed ? 'PASS' : 'FAIL'}
                    </span>
                  </td>
                  <td className="p-2 text-xs text-slate-400 max-w-xs truncate">{r.verification?.expected ?? '—'}</td>
                  <td className="p-2 text-xs text-slate-400 max-w-xs truncate">{r.verification?.observed ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
