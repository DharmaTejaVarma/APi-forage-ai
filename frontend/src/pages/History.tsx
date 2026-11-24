import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { History as HistoryIcon, CheckCircle2, XCircle, PauseCircle, Clock } from 'lucide-react';
import { api } from '../api/client';
import { WorkflowExecution } from '../types';

export const History: React.FC = () => {
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const summary = await api.getDashboardSummary();
        // Fallback or load from recent
        setExecutions(summary.recent_executions as any);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

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
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <HistoryIcon className="w-5 h-5 text-indigo-400" />
          Workflow Execution History
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Review historical execution traces, duration, Rule 8 human approval actions, and step telemetry.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Execution ID</th>
                <th className="py-3 px-4">Workflow</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Rule 8 Gate</th>
                <th className="py-3 px-4">Created Time</th>
                <th className="py-3 px-4 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {executions.map((ex) => (
                <tr key={ex.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-4 font-mono text-indigo-400">#{ex.id}</td>
                  <td className="py-3 px-4 font-medium text-white">
                    {(ex as any).workflow_title || `Workflow #${ex.workflow_id}`}
                  </td>
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
                    {ex.created_at ? new Date(ex.created_at).toLocaleString() : '—'}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <Link
                      to={`/executions/${ex.id}`}
                      className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-400 font-medium text-xs transition-colors"
                    >
                      Inspect Execution →
                    </Link>
                  </td>
                </tr>
              ))}

              {executions.length === 0 && !loading && (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500">
                    No execution records found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
