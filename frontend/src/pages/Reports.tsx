import React, { useEffect, useState } from 'react';
import { FileBarChart, Shield, Filter, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import { AuditLog } from '../types';
import { useAuth } from '../context/AuthContext';

export const Reports: React.FC = () => {
  const { isAdmin } = useAuth();
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [adminStats, setAdminStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      if (isAdmin) {
        const stats = await api.getAdminStats();
        setAdminStats(stats);
        const logs = await api.getAdminAuditLogs(50, actionFilter || undefined);
        setAuditLogs(logs);
      }
    } catch (err) {
      console.error('Failed to load reports/audit logs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [actionFilter, isAdmin]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <FileBarChart className="w-5 h-5 text-indigo-400" />
            System Reports & Audit Trail
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Complete compliance trail logging all workflow executions, authorization approvals, and AI agent repairs.
          </p>
        </div>

        <button
          onClick={loadData}
          className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 flex items-center gap-1.5 transition-colors self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Admin Stats Grid */}
      {isAdmin && adminStats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="text-xs text-slate-400 mb-1">Total Users</div>
            <div className="text-2xl font-bold text-white">{adminStats.total_users}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="text-xs text-slate-400 mb-1">Total Workflows</div>
            <div className="text-2xl font-bold text-indigo-400">{adminStats.total_workflows}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="text-xs text-slate-400 mb-1">Total Executions</div>
            <div className="text-2xl font-bold text-cyan-400">{adminStats.total_executions}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="text-xs text-slate-400 mb-1">Audit Log Entries</div>
            <div className="text-2xl font-bold text-emerald-400">{adminStats.total_audit_logs}</div>
          </div>
        </div>
      )}

      {/* Audit Logs Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl space-y-4">
        <div className="p-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <h3 className="font-semibold text-sm text-white flex items-center gap-2">
            <Shield className="w-4 h-4 text-amber-400" />
            Audit Trail Records
          </h3>

          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-slate-500" />
            <select
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Actions</option>
              <option value="connection_created">connection_created</option>
              <option value="workflow_execution_started">workflow_execution_started</option>
              <option value="step_approved">step_approved (Rule 8)</option>
              <option value="step_rejected">step_rejected</option>
              <option value="ai_fix_applied">ai_fix_applied (Rule 9)</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-4">ID</th>
                <th className="py-2.5 px-4">Action</th>
                <th className="py-2.5 px-4">User</th>
                <th className="py-2.5 px-4">Resource</th>
                <th className="py-2.5 px-4">Details</th>
                <th className="py-2.5 px-4 text-right">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {auditLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-800/40 font-mono text-[11px]">
                  <td className="py-2.5 px-4 text-slate-500">#{log.id}</td>
                  <td className="py-2.5 px-4">
                    <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-bold">
                      {log.action}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-slate-300">User #{log.user_id || 'System'}</td>
                  <td className="py-2.5 px-4 text-slate-400">
                    {log.resource_type ? `${log.resource_type}:${log.resource_id}` : '—'}
                  </td>
                  <td className="py-2.5 px-4 text-slate-400 max-w-xs truncate">
                    {log.details ? JSON.stringify(log.details) : '—'}
                  </td>
                  <td className="py-2.5 px-4 text-right text-slate-500">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}

              {auditLogs.length === 0 && !loading && (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500">
                    {isAdmin
                      ? 'No audit records matching filter.'
                      : 'Audit logs access requires administrator privileges.'}
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
