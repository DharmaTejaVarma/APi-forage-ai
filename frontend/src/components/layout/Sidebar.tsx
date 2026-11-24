import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Network,
  Search,
  Sparkles,
  GitFork,
  History,
  FileBarChart,
  Settings,
  Shield,
  Layers,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export const Sidebar: React.FC = () => {
  const { isAdmin } = useAuth();

  const links = [
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/generator', label: 'AI Generator', icon: Sparkles },
    { to: '/builder', label: 'Workflow Builder', icon: GitFork },
    { to: '/connections', label: 'API Connections', icon: Network },
    { to: '/explorer', label: 'API Explorer', icon: Search },
    { to: '/history', label: 'Execution History', icon: History },
    { to: '/reports', label: 'Reports & Logs', icon: FileBarChart },
    { to: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
      <div className="h-16 flex items-center px-6 border-b border-slate-800 gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Layers className="w-5 h-5 text-white" />
        </div>
        <div>
          <span className="font-bold text-lg bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
            APIForge AI
          </span>
          <span className="block text-[10px] text-cyan-400 font-mono tracking-wider">LOCAL AGENTIC</span>
        </div>
      </div>

      <nav className="flex-1 p-4 space-y-1.5 overflow-y-auto">
        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-3 mb-2">
          Orchestration
        </div>
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              <span>{link.label}</span>
            </NavLink>
          );
        })}

        {isAdmin && (
          <div className="pt-4 mt-4 border-t border-slate-800/80">
            <div className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider px-3 mb-2 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5" />
              <span>Admin Center</span>
            </div>
            <NavLink
              to="/reports?admin=true"
              className={({ isActive }) =>
                `flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`
              }
            >
              <FileBarChart className="w-4 h-4 text-amber-400" />
              <span>Audit Logs</span>
            </NavLink>
          </div>
        )}
      </nav>

      <div className="p-4 border-t border-slate-800 text-xs text-slate-400 flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Ollama 11434
        </span>
        <span className="font-mono text-[10px] text-slate-400">qwen2.5:7b</span>
      </div>
    </aside>
  );
};
