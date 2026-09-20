import { useEffect, useState } from 'react';

export const CommandPalette = () => {
    const [open, setOpen] = useState(false);

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setOpen(p => !p);
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);

    if (!open) return null;
    return (
        <div className="fixed inset-0 bg-black/50 flex justify-center pt-20">
            <div className="bg-slate-900 w-96 p-4 border border-slate-700 rounded shadow-xl">
                 <h3 className="text-slate-400 mb-2">Actions</h3>
                 <button className="block w-full text-left p-2 hover:bg-slate-800">Interrupt Run</button>
            </div>
        </div>
    );
};
