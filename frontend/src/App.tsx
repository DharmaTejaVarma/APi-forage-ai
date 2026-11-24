import { useEffect, useState } from 'react';
import { fetchHealth } from './api/health';
import { HealthResponse } from './types/health';
import {
  Server,
  Database,
  Cpu,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Sparkles,
  Layers,
  Terminal,
  Activity
} from 'lucide-react';

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchHealth();
      setHealth(data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err: any) {
      setError(err?.message || 'Failed to connect to backend server');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-10 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <Sparkles className="h-5 w-5 text-slate-950 font-bold" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                APIForge AI
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                  v1.0.0 • Phase 0
                </span>
              </h1>
              <p className="text-xs text-slate-400">Autonomous API Workflow Generator with Local AI</p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={loadStatus}
              disabled={loading}
              className="flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium border border-slate-700 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin text-emerald-400' : ''}`} />
              <span>{loading ? 'Checking...' : 'Refresh Status'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-6xl w-full mx-auto px-6 py-10 flex-1 space-y-8">
        {/* Banner Section */}
        <section className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900/80 to-slate-950 p-8 shadow-xl">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2">
              <h2 className="text-2xl font-bold text-white tracking-tight">
                System Diagnostics & Infrastructure
              </h2>
              <p className="text-slate-400 text-sm max-w-2xl">
                APIForge AI converts natural-language instructions into deterministic, executable DAG workflows
                using local Ollama models and SQLite with zero external cloud dependencies.
              </p>
            </div>
            <div className="flex items-center gap-3 self-start md:self-auto">
              <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60">
                <span className="relative flex h-3 w-3">
                  <span
                    className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                      health?.status === 'healthy'
                        ? 'bg-emerald-400'
                        : health?.status === 'degraded'
                        ? 'bg-amber-400'
                        : 'bg-rose-400'
                    }`}
                  ></span>
                  <span
                    className={`relative inline-flex rounded-full h-3 w-3 ${
                      health?.status === 'healthy'
                        ? 'bg-emerald-500'
                        : health?.status === 'degraded'
                        ? 'bg-amber-500'
                        : 'bg-rose-500'
                    }`}
                  ></span>
                </span>
                <span className="text-sm font-semibold capitalize text-slate-200">
                  {health ? health.status : loading ? 'Detecting...' : 'Offline'}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Error State */}
        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-5 flex items-start space-x-3 text-rose-300">
            <AlertCircle className="h-6 w-6 flex-shrink-0 text-rose-400 mt-0.5" />
            <div>
              <h3 className="font-semibold text-rose-200">Backend Connectivity Error</h3>
              <p className="text-sm mt-1 text-rose-300/90">{error}</p>
              <p className="text-xs mt-2 text-rose-400 font-mono">
                Ensure FastAPI server is running on port 8000 (uvicorn app.main:app --port 8000).
              </p>
            </div>
          </div>
        )}

        {/* Status Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Backend Status */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 flex flex-col justify-between shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="h-10 w-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                  <Server className="h-5 w-5" />
                </div>
                {health?.services.backend.status === 'ok' ? (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Operational
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                    <AlertCircle className="h-3.5 w-3.5" /> Disconnected
                  </span>
                )}
              </div>
              <div>
                <h3 className="font-semibold text-white">FastAPI Backend</h3>
                <p className="text-xs text-slate-400 mt-1">Python 3.11 • Asynchronous REST API</p>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-800/80 space-y-2 text-xs">
              <div className="flex justify-between text-slate-400">
                <span>Version</span>
                <span className="font-mono text-slate-300">{health?.version || '1.0.0'}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Port</span>
                <span className="font-mono text-slate-300">8000</span>
              </div>
            </div>
          </div>

          {/* Database Status */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 flex flex-col justify-between shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="h-10 w-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                  <Database className="h-5 w-5" />
                </div>
                {health?.services.database.connected ? (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Connected
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                    <AlertCircle className="h-3.5 w-3.5" /> Disconnected
                  </span>
                )}
              </div>
              <div>
                <h3 className="font-semibold text-white">SQLite Database</h3>
                <p className="text-xs text-slate-400 mt-1">SQLAlchemy 2.0 • WAL Mode • Foreign Keys</p>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-800/80 space-y-2 text-xs">
              <div className="flex justify-between text-slate-400">
                <span>Dialect</span>
                <span className="font-mono text-slate-300">{health?.services.database.dialect || 'sqlite'}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Journal Mode</span>
                <span className="font-mono text-emerald-400 font-semibold">WAL</span>
              </div>
            </div>
          </div>

          {/* Ollama Local AI Status */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 flex flex-col justify-between shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="h-10 w-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                  <Cpu className="h-5 w-5" />
                </div>
                {health?.services.ollama.connected ? (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Online
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                    <AlertCircle className="h-3.5 w-3.5" /> Offline
                  </span>
                )}
              </div>
              <div>
                <h3 className="font-semibold text-white">Local Ollama AI</h3>
                <p className="text-xs text-slate-400 mt-1">Local inference • No cloud dependencies</p>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-800/80 space-y-2 text-xs">
              <div className="flex justify-between text-slate-400">
                <span>Endpoint</span>
                <span className="font-mono text-slate-300">{health?.services.ollama.url || 'http://localhost:11434'}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Models Detected</span>
                <span className="font-mono text-purple-300 font-semibold">
                  {health?.services.ollama.available_models?.length ?? 0}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* AI Models Specification Section */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <Layers className="h-4 w-4 text-emerald-400" />
              Configured AI Models
            </h3>
            {lastUpdated && (
              <span className="text-xs text-slate-500 font-mono">Last verified: {lastUpdated}</span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Chat Model Card */}
            <div className="p-4 rounded-lg bg-slate-900 border border-slate-800/80 flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-200">Workflow Planning & Chat</span>
                  {health?.services.ollama.models?.chat_model?.available ? (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                      Ready
                    </span>
                  ) : health?.services.ollama.models?.chat_model?.fallback_available ? (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium">
                      Fallback Active
                    </span>
                  ) : (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-medium">
                      Missing
                    </span>
                  )}
                </div>
                <p className="text-xs font-mono text-slate-400">
                  {health?.services.ollama.models?.chat_model?.name || 'qwen2.5:7b-instruct'}
                </p>
                {health?.services.ollama.models?.chat_model?.fallback_available && !health?.services.ollama.models?.chat_model?.available && (
                  <p className="text-[11px] text-amber-400/90 font-mono">
                    Using fallback: {health?.services.ollama.models?.chat_model?.fallback_name}
                  </p>
                )}
              </div>
              <div className="h-8 w-8 rounded bg-slate-800 flex items-center justify-center text-slate-400">
                <Terminal className="h-4 w-4" />
              </div>
            </div>

            {/* Embedding Model Card */}
            <div className="p-4 rounded-lg bg-slate-900 border border-slate-800/80 flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-200">Semantic Search & Embeddings</span>
                  {health?.services.ollama.models?.embed_model?.available ? (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                      Ready
                    </span>
                  ) : (
                    <span className="text-[10px] px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-medium">
                      Missing
                    </span>
                  )}
                </div>
                <p className="text-xs font-mono text-slate-400">
                  {health?.services.ollama.models?.embed_model?.name || 'nomic-embed-text'}
                </p>
              </div>
              <div className="h-8 w-8 rounded bg-slate-800 flex items-center justify-center text-slate-400">
                <Activity className="h-4 w-4" />
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 bg-slate-900/30 px-6 py-4 text-center text-xs text-slate-500">
        APIForge AI • Phase 0: Environment Setup & Project Skeleton Complete
      </footer>
    </div>
  );
}
