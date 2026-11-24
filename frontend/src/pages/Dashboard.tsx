import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  GitFork,
  Play,
  Sparkles,
  Network,
  CheckCircle2,
  XCircle,
  PauseCircle,
  Clock,
  ArrowRight,
  TrendingUp,
  ShieldAlert,
} from 'lucide-react';
import { api } from '../api/client';
import { DashboardSummary } from '../types';

export const Dashboard: React.FC = () => {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    async function loadData() {
      try {
        const data = await api.getDashboardSummary();
        setSummary(data);
      } catch (err) {
        console.error('Failed to load dashboard:', err);
      } finally {
        // loaded
      }
    }
    loadData();
  }, []);

  const handleLaunchDemo = () => {
    navigate('/generator?demo=true');
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            <CheckCircle2 className="w-3.5 h-3.5" /> Completed
          </span>
        );
      case 'waiting_approval':
        return (
          <span className="flex items-center gap-1 text-xs text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20 animate-pulse">
            <PauseCircle className="w-3.5 h-3.5" /> Waiting Approval
          </span>
        );
      case 'failed':
        return (
          <span className="flex items-center gap-1 text-xs text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
            <XCircle className="w-3.5 h-3.5" /> Failed
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1 text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
            <Clock className="w-3.5 h-3.5" /> {status}
          </span>
        );
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Top Banner: Demonstration Scenario */}
      <div className="rounded-2xl p-6 bg-gradient-to-r from-indigo-950/80 via-slate-900 to-slate-900 border border-indigo-500/30 shadow-2xl relative overflow-hidden">
        <div className="absolute right-0 top-0 bottom-0 w-96 bg-gradient-to-l from-indigo-500/10 to-transparent pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                CORE CAPABILITY DEMO
              </span>
              <span className="text-xs text-slate-400">Non-Negotiable Rule 8 Enforced</span>
            </div>
            <h2 className="text-xl font-bold text-white">
              E-Commerce Order with Discount Calculation
            </h2>
            <p className="text-sm text-slate-300 max-w-2xl">
              "Fetch product 5, calculate a 10% discount using SimpleEval, and submit the purchase order ORD-xxxx with mandatory human approval before POST."
            </p>
          </div>
          <button
            onClick={handleLaunchDemo}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-600 hover:to-cyan-600 text-white font-medium text-sm shadow-lg shadow-indigo-500/25 transition-all shrink-0"
          >
            <Sparkles className="w-4 h-4" />
            Launch Demo Workflow
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Workflows</span>
            <GitFork className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-white">{summary?.total_workflows ?? 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">Saved DAG pipelines</div>
        </div>

        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Total Executions</span>
            <Play className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold text-white">{summary?.total_executions ?? 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">Pipeline execution runs</div>
        </div>

        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Success Rate</span>
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-400">{summary?.success_rate ?? 100}%</div>
          <div className="text-[11px] text-slate-400 mt-1">
            {summary?.completed_executions ?? 0} successful / {summary?.failed_executions ?? 0} failed
          </div>
        </div>

        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Awaiting Approval</span>
            <ShieldAlert className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-amber-400">{summary?.waiting_approval ?? 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">Rule 8 Human Gate</div>
        </div>

        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">API Endpoints</span>
            <Network className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-white">{summary?.total_endpoints ?? 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">
            Across {summary?.total_connections ?? 0} connections
          </div>
        </div>
      </div>

      {/* Quick Action Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link
          to="/generator"
          className="p-5 rounded-xl bg-slate-900 border border-slate-800 hover:border-indigo-500/40 transition-all group"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-400 border border-indigo-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-indigo-400 transition-colors" />
          </div>
          <h3 className="font-semibold text-white text-sm mb-1">AI Workflow Generator</h3>
          <p className="text-xs text-slate-400">
            Convert plain English instructions into multi-step DAG plans with local Ollama.
          </p>
        </Link>

        <Link
          to="/builder"
          className="p-5 rounded-xl bg-slate-900 border border-slate-800 hover:border-cyan-500/40 transition-all group"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center text-cyan-400 border border-cyan-500/20">
              <GitFork className="w-5 h-5" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-cyan-400 transition-colors" />
          </div>
          <h3 className="font-semibold text-white text-sm mb-1">Visual Workflow Canvas</h3>
          <p className="text-xs text-slate-400">
            Design and inspect topological execution nodes, parameters, and approval gates.
          </p>
        </Link>

        <Link
          to="/connections"
          className="p-5 rounded-xl bg-slate-900 border border-slate-800 hover:border-purple-500/40 transition-all group"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center text-purple-400 border border-purple-500/20">
              <Network className="w-5 h-5" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-purple-400 transition-colors" />
          </div>
          <h3 className="font-semibold text-white text-sm mb-1">API Connections & OpenAPI</h3>
          <p className="text-xs text-slate-400">
            Connect REST services, import OpenAPI 3.0 specifications, and generate embeddings.
          </p>
        </Link>
      </div>

      {/* Recent Executions Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="font-semibold text-sm text-white flex items-center gap-2">
            <Play className="w-4 h-4 text-indigo-400" />
            Recent Executions
          </h3>
          <Link to="/history" className="text-xs text-indigo-400 hover:text-indigo-300 font-medium">
            View All History →
          </Link>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Execution ID</th>
                <th className="py-3 px-4">Workflow</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Approval Gate</th>
                <th className="py-3 px-4">Started</th>
                <th className="py-3 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {summary?.recent_executions?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500">
                    No executions recorded yet. Launch the demo above to start!
                  </td>
                </tr>
              ) : (
                summary?.recent_executions?.map((ex) => (
                  <tr key={ex.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 font-mono text-slate-300">#{ex.id}</td>
                    <td className="py-3 px-4 font-medium text-white">{ex.workflow_title}</td>
                    <td className="py-3 px-4">{getStatusBadge(ex.status)}</td>
                    <td className="py-3 px-4">
                      {ex.requires_approval ? (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 font-mono">
                          {ex.approval_status}
                        </span>
                      ) : (
                        <span className="text-slate-500 text-[11px]">N/A</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-slate-400">
                      {ex.created_at ? new Date(ex.created_at).toLocaleTimeString() : '—'}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <Link
                        to={`/executions/${ex.id}`}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-indigo-400 font-medium text-[11px] transition-colors"
                      >
                        Inspect
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
