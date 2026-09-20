import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';

export function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-lg bg-slate-900 p-4 border border-slate-700 shadow-xl">
        <input 
          autoFocus
          className="w-full bg-transparent border-b border-slate-700 p-2 text-white outline-none"
          placeholder="Search commands..."
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              navigate('/');
              setIsOpen(false);
            }
          }}
        />
        <div className="mt-2 space-y-1">
          <button onClick={() => { navigate('/'); setIsOpen(false); }} className="block w-full text-left p-2 hover:bg-slate-800 rounded">Go to Overview</button>
          <button onClick={() => { navigate('/runs'); setIsOpen(false); }} className="block w-full text-left p-2 hover:bg-slate-800 rounded">Go to Runs</button>
        </div>
      </div>
    </div>
  );
}
