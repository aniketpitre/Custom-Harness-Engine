import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function ApprovalsPage() {
  const [approvals, setApprovals] = useState<any[]>([]);

  useEffect(() => {
    api.get('/approvals').then(setApprovals).catch(() => setApprovals([]));
  }, []);

  const decide = (id: string, decision: 'approve' | 'deny') => {
    api.post(`/approvals/${id}/decide`, { decision }).then(() => {
      setApprovals((prev) => prev.filter((a) => a.id !== id));
    });
  };

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Approval Gate</h2>
      <p className="text-xs text-slate-500">Pending REQUIRE_APPROVAL actions. Approve or deny from here — mirrors Telegram approval but from the dashboard.</p>

      {approvals.length === 0 ? (
        <div className="rounded border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-500">
          No pending approvals
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <div key={a.id} className="rounded border border-yellow-800 bg-slate-900/50 p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-medium">{a.kind}</div>
                  <div className="text-sm text-slate-400 mt-1">{a.description}</div>
                  {a.risk_tier && (
                    <span className={`inline-block mt-2 rounded px-2 py-0.5 text-xs font-medium ${
                      a.risk_tier === 'R4' ? 'text-red-400 bg-red-400/10' :
                      a.risk_tier === 'R3' ? 'text-orange-400 bg-orange-400/10' :
                      a.risk_tier === 'R2' ? 'text-yellow-400 bg-yellow-400/10' :
                      'text-green-400 bg-green-400/10'
                    }`}>
                      {a.risk_tier}
                    </span>
                  )}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => decide(a.id, 'approve')} className="rounded bg-green-600 px-3 py-1.5 text-xs">Approve</button>
                  <button onClick={() => decide(a.id, 'deny')} className="rounded bg-red-600 px-3 py-1.5 text-xs">Deny</button>
                </div>
              </div>
              <div className="text-xs text-slate-600 mt-2">{a.created_at}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
