import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  CheckCircle2,
  XCircle,
  PauseCircle,
  Clock,
  ShieldAlert,
  Sparkles,
  RefreshCw,
  Terminal,
  Layers,
  Wrench,
  Check,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import { WorkflowExecution, ErrorDiagnosis, CandidateFix } from '../types';

export const Execution: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // AI Error Recovery state
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnosis, setDiagnosis] = useState<ErrorDiagnosis | null>(null);
  const [selectedFix, setSelectedFix] = useState<CandidateFix | null>(null);

  const fetchExecution = async () => {
    if (!id) return;
    try {
      setRefreshing(true);
      const data = await api.getExecution(Number(id));
      setExecution(data);
      if (data.error_details?.ai_diagnosis) {
        setDiagnosis(data.error_details.ai_diagnosis);
      }
    } catch (err) {
      console.error('Failed to load execution:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchExecution();
    const interval = setInterval(() => {
      // Auto-poll if running or waiting
      if (execution?.status === 'running' || execution?.status === 'pending') {
        fetchExecution();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [id, execution?.status]);

  const handleApprove = async () => {
    if (!execution) return;
    setActionLoading(true);
    try {
      const updated = await api.approveExecution(execution.id);
      setExecution(updated);
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!execution) return;
    if (!window.confirm('Reject this pending step and cancel the workflow?')) return;
    setActionLoading(true);
    try {
      const updated = await api.rejectExecution(execution.id);
      setExecution(updated);
    } catch (err: any) {
      alert(`Rejection failed: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDiagnose = async () => {
    if (!execution) return;
    setDiagnosing(true);
    try {
      const res = await api.diagnoseExecution(execution.id);
      setDiagnosis(res);
      if (res.candidate_fixes?.length > 0) {
        setSelectedFix(res.candidate_fixes[0]);
      }
    } catch (err: any) {
      alert(`Diagnosis failed: ${err.message}`);
    } finally {
      setDiagnosing(false);
    }
  };

  const handleApplyFix = async () => {
    if (!execution || !selectedFix) return;
    if (
      !window.confirm(
        `Non-Negotiable Rule 9: Apply candidate fix '${selectedFix.title}' to the workflow and resume DAG execution?`
      )
    )
      return;

    setActionLoading(true);
    try {
      const updated = await api.applyFix(
        execution.id,
        selectedFix.target_node_id,
        selectedFix.patch,
        true
      );
      setExecution(updated);
      setDiagnosis(null);
      setSelectedFix(null);
    } catch (err: any) {
      alert(`Apply fix failed: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
            <CheckCircle2 className="w-4 h-4" /> COMPLETED
          </span>
        );
      case 'waiting_approval':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-400 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20 animate-pulse">
            <PauseCircle className="w-4 h-4" /> WAITING FOR APPROVAL (RULE 8)
          </span>
        );
      case 'failed':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-rose-400 bg-rose-500/10 px-3 py-1 rounded-full border border-rose-500/20">
            <XCircle className="w-4 h-4" /> FAILED
          </span>
        );
      case 'running':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-cyan-400 bg-cyan-500/10 px-3 py-1 rounded-full border border-cyan-500/20">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" /> RUNNING
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 bg-slate-800 px-3 py-1 rounded-full">
            <Clock className="w-4 h-4" /> {status?.toUpperCase()}
          </span>
        );
    }
  };

  if (loading && !execution) {
    return (
      <div className="py-20 text-center text-slate-400">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
        Loading execution state...
      </div>
    );
  }

  if (!execution) {
    return (
      <div className="py-20 text-center text-slate-400">
        Execution #{id} not found.{' '}
        <Link to="/history" className="text-indigo-400 underline">
          Back to History
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Execution Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="font-mono text-xs text-indigo-400 font-bold">
              EXECUTION #{execution.id}
            </span>
            <span className="text-xs text-slate-500">|</span>
            <Link
              to={`/builder?id=${execution.workflow_id}`}
              className="text-xs text-slate-400 hover:text-white underline font-mono"
            >
              Workflow #{execution.workflow_id}
            </Link>
          </div>
          <h2 className="text-xl font-bold text-white flex items-center gap-3">
            Pipeline Execution Monitor
          </h2>
          <div className="text-xs text-slate-400 mt-1 flex items-center gap-3">
            <span>Started: {execution.started_at ? new Date(execution.started_at).toLocaleTimeString() : '—'}</span>
            {execution.completed_at && (
              <span>Completed: {new Date(execution.completed_at).toLocaleTimeString()}</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {getStatusBadge(execution.status)}
          <button
            onClick={fetchExecution}
            disabled={refreshing}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Refresh Status"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* RULE 8 HUMAN APPROVAL MODAL / BANNER */}
      {execution.status === 'waiting_approval' && (
        <div className="rounded-2xl p-6 bg-gradient-to-r from-amber-950/80 via-slate-900 to-slate-900 border-2 border-amber-500 shadow-2xl shadow-amber-500/10 space-y-4 animate-in fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center shrink-0 text-amber-400">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  RULE 8 HUMAN-IN-THE-LOOP APPROVAL REQUIRED
                </span>
                <span className="text-xs text-amber-400 font-mono">
                  Pending Step: '{execution.pending_approval_step}'
                </span>
              </div>
              <h3 className="text-lg font-bold text-white mt-1">
                Authorization Required Before Performing State-Modifying Operation
              </h3>
              <p className="text-xs text-slate-300 mt-1 max-w-2xl">
                The DAG execution has paused safely before executing a POST/PUT/DELETE operation.
                Review the computed step payload below and authorize whether to proceed with sending the request.
              </p>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-amber-500/30">
            <button
              onClick={handleReject}
              disabled={actionLoading}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-rose-950/60 text-rose-300 border border-rose-500/30 text-xs font-semibold transition-all flex items-center gap-1.5 disabled:opacity-50"
            >
              <X className="w-4 h-4" />
              Reject & Cancel Execution
            </button>
            <button
              onClick={handleApprove}
              disabled={actionLoading}
              className="px-6 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-lg shadow-emerald-600/30 transition-all flex items-center gap-2 disabled:opacity-50"
            >
              <Check className="w-4 h-4" />
              Authorize Step & Resume DAG
            </button>
          </div>
        </div>
      )}

      {/* RULE 9 AI ERROR RECOVERY AGENT PANEL */}
      {execution.status === 'failed' && (
        <div className="rounded-2xl p-6 bg-gradient-to-r from-rose-950/80 via-slate-900 to-slate-900 border border-rose-500/50 shadow-2xl space-y-5 animate-in fade-in">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-500/20 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0">
                <XCircle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Execution Encountered An Error</h3>
                <p className="text-xs text-rose-300 font-mono">
                  {execution.error_details?.category || 'ERROR'}: {execution.error_details?.message}
                </p>
              </div>
            </div>

            <button
              onClick={handleDiagnose}
              disabled={diagnosing}
              className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-indigo-600/25 transition-all shrink-0 disabled:opacity-50"
            >
              <Sparkles className="w-4 h-4" />
              {diagnosing ? 'Analyzing Root Cause...' : 'Diagnose with AI Agent'}
            </button>
          </div>

          {/* AI Diagnosis Details */}
          {diagnosis && (
            <div className="bg-slate-950/80 rounded-xl p-5 border border-indigo-500/30 space-y-4">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  AI ROOT CAUSE DIAGNOSIS (qwen2.5:7b)
                </span>
                <span className="text-[10px] text-amber-400 font-mono">
                  RULE 9: Explicit User Confirmation Required
                </span>
              </div>

              <div>
                <h4 className="text-sm font-bold text-white mb-1">{diagnosis.root_cause}</h4>
                <p className="text-xs text-slate-300 leading-relaxed">{diagnosis.explanation}</p>
              </div>

              {/* Candidate Fixes */}
              <div className="space-y-2">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
                  Proposed Candidate Fixes:
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {diagnosis.candidate_fixes?.map((fix) => (
                    <div
                      key={fix.fix_id}
                      onClick={() => setSelectedFix(fix)}
                      className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                        selectedFix?.fix_id === fix.fix_id
                          ? 'bg-indigo-950/60 border-indigo-500 shadow-md shadow-indigo-500/20'
                          : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-semibold text-xs text-white">{fix.title}</span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-cyan-300">
                          {fix.change_type}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 mb-2">{fix.description}</p>
                      <pre className="p-2 rounded bg-slate-950 text-[10px] font-mono text-emerald-400 overflow-x-auto">
                        Patch: {JSON.stringify(fix.patch, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>

              {selectedFix && (
                <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
                  <button
                    onClick={handleApplyFix}
                    disabled={actionLoading}
                    className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-600 hover:to-cyan-600 text-white text-xs font-bold shadow-lg shadow-emerald-500/20 transition-all flex items-center gap-2 disabled:opacity-50"
                  >
                    <Wrench className="w-4 h-4" />
                    {actionLoading ? 'Applying & Resuming...' : `Confirm & Apply Fix '${selectedFix.title}'`}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step Results Output Grid */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Layers className="w-4 h-4 text-indigo-400" />
          Step Outputs & Transferred State
        </h3>

        <div className="space-y-3">
          {Object.entries(execution.step_results || {}).map(([stepId, res]) => (
            <div key={stepId} className="bg-slate-950 rounded-xl border border-slate-800 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-indigo-300">{stepId}</span>
                  {res.status === 'completed' ? (
                    <span className="flex items-center gap-1 text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                      <CheckCircle2 className="w-3 h-3" /> Completed
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
                      <XCircle className="w-3 h-3" /> Failed
                    </span>
                  )}
                </div>

                <div className="text-[11px] font-mono text-slate-400">
                  {res.status_code && <span className="mr-3">HTTP {res.status_code}</span>}
                  {res.elapsed_ms && <span>{res.elapsed_ms}ms</span>}
                </div>
              </div>

              <pre className="p-3 rounded-lg bg-slate-900 text-xs font-mono text-slate-300 overflow-x-auto max-h-48">
                {JSON.stringify(res.output, null, 2)}
              </pre>
            </div>
          ))}

          {Object.keys(execution.step_results || {}).length === 0 && (
            <div className="py-6 text-center text-xs text-slate-500">
              No steps completed yet.
            </div>
          )}
        </div>
      </div>

      {/* Execution Telemetry Logs */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-3">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Terminal className="w-4 h-4 text-cyan-400" />
          Execution Telemetry Logs
        </h3>

        <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs space-y-1.5 max-h-60 overflow-y-auto">
          {execution.execution_logs?.map((log, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-slate-500 text-[10px] shrink-0">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              <span
                className={`text-[10px] px-1 rounded font-bold shrink-0 ${
                  log.level === 'ERROR'
                    ? 'text-rose-400 bg-rose-500/10'
                    : log.level === 'WARNING'
                    ? 'text-amber-400 bg-amber-500/10'
                    : 'text-indigo-400 bg-indigo-500/10'
                }`}
              >
                {log.level}
              </span>
              {log.step_id && <span className="text-cyan-400 shrink-0">[{log.step_id}]</span>}
              <span className="text-slate-300 break-all">{log.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
