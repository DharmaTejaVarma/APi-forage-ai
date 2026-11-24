import React from 'react';
import { LogOut, User as UserIcon, Shield } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();

  return (
    <header className="h-16 bg-slate-900/80 backdrop-blur-md border-b border-slate-800 px-6 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-4">
        <h1 className="text-sm font-medium text-slate-300">
          Intelligent Local API Workflow Platform
        </h1>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-xs">
          {user?.role === 'admin' ? (
            <span className="flex items-center gap-1.5 text-amber-400 font-medium">
              <Shield className="w-3.5 h-3.5" /> Admin
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-slate-300 font-medium">
              <UserIcon className="w-3.5 h-3.5 text-indigo-400" /> User
            </span>
          )}
          <span className="text-slate-400">|</span>
          <span className="text-slate-300">{user?.email}</span>
        </div>

        <button
          onClick={logout}
          title="Sign Out"
          className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
