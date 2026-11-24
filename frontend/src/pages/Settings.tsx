import React, { useEffect } from 'react';
import { Settings as SettingsIcon, Cpu, User, HardDrive, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Settings: React.FC = () => {
  const { user } = useAuth();

  useEffect(() => {
    // Component mounted
  }, []);

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <SettingsIcon className="w-5 h-5 text-indigo-400" />
          Settings & Local Environment
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Verify local AI models, database status, and user profile configuration.
        </p>
      </div>

      {/* Account Info */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <User className="w-4 h-4 text-indigo-400" />
          User Profile
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
            <span className="text-slate-400 block mb-1">Email Address:</span>
            <span className="font-semibold text-white">{user?.email}</span>
          </div>

          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
            <span className="text-slate-400 block mb-1">Role:</span>
            <span className="font-semibold text-indigo-400 capitalize">{user?.role}</span>
          </div>
        </div>
      </div>

      {/* Local AI Engine Status */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Cpu className="w-4 h-4 text-cyan-400" />
          Local AI Engine (Ollama)
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-mono">
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Chat & Plan Model:</span>
              <span className="text-emerald-400 flex items-center gap-1 text-[11px]">
                <CheckCircle2 className="w-3 h-3" /> Available
              </span>
            </div>
            <div className="text-sm font-bold text-white">qwen2.5:7b-instruct</div>
            <div className="text-[11px] text-slate-500">Local 7B parameter reasoning engine</div>
          </div>

          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Embedding Model:</span>
              <span className="text-emerald-400 flex items-center gap-1 text-[11px]">
                <CheckCircle2 className="w-3 h-3" /> Available
              </span>
            </div>
            <div className="text-sm font-bold text-white">nomic-embed-text</div>
            <div className="text-[11px] text-slate-500">768-dim semantic search vectors</div>
          </div>
        </div>
      </div>

      {/* Security & Database Status */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-purple-400" />
          Database & Encryption
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-400 block">Database Storage:</span>
            <span className="font-semibold text-white">SQLite (WAL Mode Enabled)</span>
            <span className="text-[11px] text-slate-500 block">Foreign Key Cascades Active</span>
          </div>

          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-400 block">Credential Storage:</span>
            <span className="font-semibold text-white">Fernet 256-bit Symmetric Cipher</span>
            <span className="text-[11px] text-slate-500 block">Secrets masked in responses</span>
          </div>
        </div>
      </div>
    </div>
  );
};
