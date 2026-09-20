import { motion } from "motion/react";

export const Layout = ({ children }: { children: React.ReactNode }) => (
  <div className="flex bg-slate-950 text-slate-100 min-h-screen">
    {/* Sidebar */}
    <nav className="w-64 border-r border-slate-800 p-4">
      <h1 className="font-bold text-xl mb-8 text-indigo-400">Harness</h1>
      <ul className="space-y-4">
        <li><a href="/" className="hover:text-indigo-300">Overview</a></li>
        <li><a href="/runs" className="hover:text-indigo-300">Runs</a></li>
        <li><a href="/analytics" className="hover:text-indigo-300">Analytics</a></li>
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
