import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function AnalyticsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [range, setRange] = useState<7 | 30 | 90>(7);

  useEffect(() => {
    api.get('/runs').then(setRuns).catch(console.error);
  }, []);

  const cutoff = new Date(Date.now() - range * 86400000).toISOString();
  const filtered = runs.filter((r) => (r.created_at ?? '') >= cutoff);
  const success = filtered.filter((r) => r.status === 'success').length;
  const failure = filtered.filter((r) => r.status === 'failure').length;

  // Policy breakdown from run receipts
  const policyBreakdown = { allow: 0, require_approval: 0, deny: 0 };
  for (const r of filtered) {
    try {
      const receipt = JSON.parse(r.run_receipt || '{}');
      const decision = receipt?.policy_decision ?? receipt?.risk_tier;
      if (decision === 'ALLOW' || decision === 'R0' || decision === 'R1') policyBreakdown.allow++;
      else if (decision === 'REQUIRE_APPROVAL' || decision === 'R2' || decision === 'R3') policyBreakdown.require_approval++;
      else if (decision === 'DENY' || decision === 'R4') policyBreakdown.deny++;
      else policyBreakdown.allow++;
    } catch { policyBreakdown.allow++; }
  }

  // Daily counts for chart
  const dailyCounts: Record<string, number> = {};
  for (const r of filtered) {
    const day = (r.created_at ?? '').slice(0, 10);
    if (day) dailyCounts[day] = (dailyCounts[day] ?? 0) + 1;
  }
  const sortedDays = Object.keys(dailyCounts).sort();
  const maxCount = Math.max(1, ...Object.values(dailyCounts));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <h2 className="text-2xl font-bold">Analytics</h2>
        <div className="flex gap-1">
          {([7, 30, 90] as const).map((d) => (
            <button
              key={d}
              onClick={() => setRange(d)}
              className={`rounded px-3 py-1 text-xs ${range === d ? 'bg-indigo-600' : 'bg-slate-800 hover:bg-slate-700'}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <StatCard label="Total Runs" value={filtered.length} />
        <StatCard label="Success" value={success} color="text-green-400" />
        <StatCard label="Failure" value={failure} color="text-red-400" />
        <StatCard label="Pass Rate" value={filtered.length ? `${Math.round((success / filtered.length) * 100)}%` : 'N/A'} color="text-indigo-400" />
      </div>

      {/* Policy breakdown — unique to Harness */}
      <div>
        <h3 className="text-lg font-semibold mb-2">Policy Decision Breakdown</h3>
        <div className="grid grid-cols-3 gap-4">
          <StatCard label="ALLOW" value={policyBreakdown.allow} color="text-green-400" />
          <StatCard label="REQUIRE_APPROVAL" value={policyBreakdown.require_approval} color="text-yellow-400" />
          <StatCard label="DENY" value={policyBreakdown.deny} color="text-red-400" />
        </div>
      </div>

      {/* Daily bar chart */}
      <div>
        <h3 className="text-lg font-semibold mb-2">Daily Run Volume</h3>
        <div className="flex items-end gap-1 h-40 rounded border border-slate-800 bg-slate-900/50 p-4">
          {sortedDays.length === 0 && <div className="text-slate-500 m-auto text-sm">No data</div>}
          {sortedDays.map((day) => (
            <div key={day} className="flex-1 flex flex-col items-center gap-1">
              <div
                className="w-full bg-indigo-500 rounded-t"
                style={{ height: `${(dailyCounts[day] / maxCount) * 100}%`, minHeight: 4 }}
                title={`${day}: ${dailyCounts[day]} runs`}
              />
              <span className="text-[10px] text-slate-500 truncate w-full text-center">{day.slice(5)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color ?? ''}`}>{value}</div>
    </div>
  );
}
