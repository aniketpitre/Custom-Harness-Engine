import { motion } from "motion/react";
import { Link } from "react-router-dom";

export const Layout = ({ children }: { children: React.ReactNode }) => (
  <div className="flex bg-slate-950 text-slate-100 min-h-screen">
    {/* Sidebar */}
    <nav className="w-64 border-r border-slate-800 p-4">
      <h1 className="font-bold text-xl mb-8 text-indigo-400">Harness</h1>
      <ul className="space-y-2">
        <li><Link to="/" className="block p-2 hover:bg-slate-900 rounded">Overview</Link></li>
        <li><Link to="/runs" className="block p-2 hover:bg-slate-900 rounded">Runs</Link></li>
        <li><Link to="/analytics" className="block p-2 hover:bg-slate-900 rounded">Analytics</Link></li>
        <li><Link to="/settings" className="block p-2 hover:bg-slate-900 rounded">Settings</Link></li>
        <li><Link to="/skills" className="block p-2 hover:bg-slate-900 rounded">Skills & Tools</Link></li>
        <li><Link to="/approvals" className="block p-2 hover:bg-slate-900 rounded">Approval Gate</Link></li>
        <li><Link to="/orchestration" className="block p-2 hover:bg-slate-900 rounded">Orchestration</Link></li>
        <li><Link to="/verification" className="block p-2 hover:bg-slate-900 rounded">Verification</Link></li>
      </ul>
    </nav>
    {/* Main */}
    <motion.main
        className="flex-1 p-8"
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.3 }}
    >
      {children}
    </motion.main>
  </div>
);

