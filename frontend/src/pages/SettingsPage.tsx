import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export function SettingsPage() {
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get('/config/schema').then(setConfig).catch(() => setConfig({}));
  }, []);

  if (!config) return <div className="text-slate-400">Loading config...</div>;

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-2xl font-bold">Settings</h2>
      {Object.keys(config).length === 0 ? (
        <p className="text-slate-500">No configuration schema available. Config fields will appear here once <code>/api/config/schema</code> is wired.</p>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); api.post('/config', config).then(() => setSaved(true)); }}>
          {Object.entries(config).map(([key, val]) => (
            <div key={key} className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">{key}</label>
              <input
                className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm outline-none"
                value={String(val ?? '')}
                onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
              />
            </div>
          ))}
          <button type="submit" className="rounded bg-indigo-600 px-4 py-2 text-sm">Save</button>
          {saved && <span className="ml-3 text-green-400 text-sm">Saved</span>}
        </form>
      )}
    </div>
  );
}
