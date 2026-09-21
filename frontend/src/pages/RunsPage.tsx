import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../lib/api';

export function RunsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'success' | 'failure'>('all');
  const [expanded, setExpanded] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.get('/runs').then(setRuns).catch(console.error);
  }, []);

  const filtered = runs.filter((r) => {
    if (filter !== 'all' && r.status !== filter) return false;
    if (search && !r.goal?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Runs</h2>

      {/* Search + Filters */}
      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm outline-none"
          placeholder="Search runs..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {(['all', 'success', 'failure'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded px-3 py-1.5 text-xs capitalize ${filter === f ? 'bg-indigo-600' : 'bg-slate-800 hover:bg-slate-700'}`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left">
            <tr>
              <th className="p-2">Goal</th>
              <th className="p-2">Status</th>
              <th className="p-2">Agent</th>
              <th className="p-2">Created</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <>
                <tr
                  key={r.id}
                  className="border-t border-slate-800 hover:bg-slate-900/50 cursor-pointer"
                  onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                >
                  <td className="p-2 max-w-xs truncate">{r.goal}</td>
                  <td className="p-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      r.status === 'success' ? 'text-green-400 bg-green-400/10' :
                      r.status === 'failure' ? 'text-red-400 bg-red-400/10' :
                      'text-yellow-400 bg-yellow-400/10'
                    }`}>{r.status}</span>
                  </td>
                  <td className="p-2 text-slate-400">{r.agent_id}</td>
                  <td className="p-2 text-slate-500 text-xs">{r.created_at}</td>
                  <td className="p-2">
                    <button
                      className="text-xs text-indigo-400 hover:underline mr-2"
                      onClick={(e) => { e.stopPropagation(); navigate(`/run/${r.id}`); }}
                    >
                      Stream
                    </button>
                    <button
                      className="text-xs text-slate-400 hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url; a.download = `run-${r.id}.json`; a.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      Export
                    </button>
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr key={`${r.id}-detail`} className="bg-slate-900">
                    <td colSpan={5} className="p-4">
                      <pre className="text-xs text-slate-300 overflow-auto max-h-64">
                        {JSON.stringify(JSON.parse(r.run_receipt || '{}'), null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
