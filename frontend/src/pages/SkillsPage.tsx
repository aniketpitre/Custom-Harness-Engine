import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function SkillsPage() {
  const [skills, setSkills] = useState<any[]>([]);
  const [candidates, setCandidates] = useState<any[]>([]);

  useEffect(() => {
    api.get('/skills').then(setSkills).catch(() => setSkills([]));
    api.get('/candidate-skills').then(setCandidates).catch(() => setCandidates([]));
  }, []);

  const toggleSkill = (id: string) => {
    api.post(`/skills/${id}/toggle`).then(() => {
      setSkills((prev) => prev.map((s) => s.id === id ? { ...s, enabled: !s.enabled } : s));
    });
  };

  const decideCandidate = (id: string, decision: 'approve' | 'reject') => {
    api.post(`/candidate-skills/${id}/decide`, { decision }).then(() => {
      setCandidates((prev) => prev.filter((c) => c.id !== id));
    });
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold mb-4">Skills & Tools</h2>
        {skills.length === 0 ? (
          <p className="text-slate-500">No skills registered. Skills will appear once <code>/api/skills</code> is wired.</p>
        ) : (
          <div className="space-y-2">
            {skills.map((s) => (
              <div key={s.id} className="flex items-center justify-between rounded border border-slate-800 bg-slate-900/50 p-3">
                <div>
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-slate-500">{s.description}</div>
                </div>
                <button
                  onClick={() => toggleSkill(s.id)}
                  className={`rounded px-3 py-1 text-xs ${s.enabled ? 'bg-green-600' : 'bg-slate-700'}`}
                >
                  {s.enabled ? 'Enabled' : 'Disabled'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Learning Queue — Harness-unique */}
      <div>
        <h3 className="text-lg font-semibold mb-2">Learning Queue</h3>
        <p className="text-xs text-slate-500 mb-3">Candidate skills pending human approval before promotion — unique to Harness Engine.</p>
        {candidates.length === 0 ? (
          <p className="text-slate-500 text-sm">No pending candidates.</p>
        ) : (
          <div className="space-y-2">
            {candidates.map((c) => (
              <div key={c.id} className="rounded border border-yellow-800 bg-yellow-900/20 p-3">
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-slate-400 mb-2">{c.description}</div>
                <div className="flex gap-2">
                  <button onClick={() => decideCandidate(c.id, 'approve')} className="rounded bg-green-600 px-3 py-1 text-xs">Approve</button>
                  <button onClick={() => decideCandidate(c.id, 'reject')} className="rounded bg-red-600 px-3 py-1 text-xs">Reject</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
