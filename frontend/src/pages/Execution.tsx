import React, { useEffect, useState, useCallback } from 'react';
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
  ArrowRight,
  Timer,
  SkipForward,
} from 'lucide-react';
import { api } from '../api/client';
import {
  Workflow,
  WorkflowExecution,
  ErrorDiagnosis,
  CandidateFix,
  ExecutionStepResult,
} from '../types';

export const Execution: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // AI Error Recovery state
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnosis, setDiagnosis] = useState<ErrorDiagnosis | null>(null);
  const [selectedFix, setSelectedFix] = useState<CandidateFix | null>(null);

  const fetchExecution = useCallback(async () => {
    if (!id) return;
    try {
      setRefreshing(true);
      const data = await api.getExecution(Number(id));
      setExecution(data);
      if (data.error_details?.ai_diagnosis) {
        setDiagnosis(data.error_details.ai_diagnosis);
      }
      if (!workflow || workflow.id !== data.workflow_id) {
        const wf = await api.getWorkflow(data.workflow_id).catch(() => null);
        if (wf) setWorkflow(wf);
      }
    } catch (err) {
      console.error('Failed to load execution:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id, workflow]);

  useEffect(() => {
    fetchExecution();
  }, [id]);

  useEffect(() => {
    if (execution?.status !== 'running' && execution?.status !== 'pending') {
      return;
    }
    const interval = setInterval(() => {
      fetchExecution();
    }, 1500);
    return () => clearInterval(interval);
  }, [execution?.status, fetchExecution]);

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

  const getStepColorBadge = (status: string) => {
    // Visual colors matching specification:
    // Grey = Pending, Blue = Running, Green = Completed, Red = Failed, Yellow = Waiting for Approval
    switch (status) {
      case 'completed':
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-300 bg-emerald-500/15 px-2.5 py-0.5 rounded-full border border-emerald-500/40">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Completed
          </span>
        );
      case 'running':
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-blue-300 bg-blue-500/20 px-2.5 py-0.5 rounded-full border border-blue-500/40">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" /> Running
          </span>
        );
      case 'waiting_approval':
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-amber-300 bg-amber-500/20 px-2.5 py-0.5 rounded-full border border-amber-500/40 animate-pulse">
            <PauseCircle className="w-3 h-3 text-amber-400" /> Waiting for Approval
          </span>
        );
      case 'failed':
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-rose-300 bg-rose-500/15 px-2.5 py-0.5 rounded-full border border-rose-500/40">
            <XCircle className="w-3 h-3 text-rose-400" /> Failed
          </span>
        );
      case 'skipped':
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-slate-400 bg-slate-800 px-2.5 py-0.5 rounded-full border border-slate-700">
            <SkipForward className="w-3 h-3" /> Skipped
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1 text-[10px] font-semibold text-slate-300 bg-slate-700/40 px-2.5 py-0.5 rounded-full border border-slate-600/60">
            <Clock className="w-3 h-3 text-slate-400" /> Pending
          </span>
        );
    }
  };

  const getHeaderStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300 bg-emerald-500/15 px-3 py-1 rounded-full border border-emerald-500/40">
            <CheckCircle2 className="w-4 h-4" /> COMPLETED
          </span>
        );
      case 'waiting_approval':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-300 bg-amber-500/20 px-3 py-1 rounded-full border border-amber-500/40 animate-pulse">
            <PauseCircle className="w-4 h-4" /> WAITING FOR APPROVAL
          </span>
        );
      case 'failed':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-rose-300 bg-rose-500/15 px-3 py-1 rounded-full border border-rose-500/40">
            <XCircle className="w-4 h-4" /> FAILED
          </span>
        );
      case 'running':
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-blue-300 bg-blue-500/20 px-3 py-1 rounded-full border border-blue-500/40">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-400 animate-ping" /> RUNNING
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 bg-slate-700/50 px-3 py-1 rounded-full border border-slate-600">
            <Clock className="w-4 h-4" /> {status?.toUpperCase()}
          </span>
        );
    }
  };

  const computeTotalDuration = (): string => {
    if (!execution?.started_at) return '—';
    const startMs = new Date(execution.started_at).getTime();
    const endMs = execution.completed_at ? new Date(execution.completed_at).getTime() : Date.now();
    const diff = Math.max(0, endMs - startMs);
    return diff >= 1000 ? `${(diff / 1000).toFixed(2)}s` : `${diff}ms`;
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

  // Merge all workflow nodes in topological order with live execution telemetry
  const orderedIds: string[] =
    (workflow?.dag_structure?.execution_order as string[] | undefined) ||
    workflow?.nodes.map((n) => n.id) ||
    Object.keys(execution.step_results || {});

  const allStepIds = Array.from(new Set([...orderedIds, ...Object.keys(execution.step_results || {})]));
  const nodeMap = new Map((workflow?.nodes || []).map((n) => [n.id, n]));
  const approvalDetails = execution.pending_approval_details;

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Execution Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="font-mono text-xs text-indigo-400 font-bold">
              EXECUTION #{execution.id}
            </span>
            <span className="text-xs text-slate-500">|</span>
            <Link
              to={`/builder?id=${execution.workflow_id}`}
              className="text-xs text-slate-300 hover:text-white underline font-mono"
            >
              Workflow #{execution.workflow_id}{workflow?.title ? `: ${workflow.title}` : ''}
            </Link>
          </div>
          <h2 className="text-xl font-bold text-white">Pipeline Execution Monitor</h2>
          <div className="text-xs text-slate-400 mt-1.5 flex flex-wrap items-center gap-4">
            <span>
              Started: <strong className="text-slate-200">{execution.started_at ? new Date(execution.started_at).toLocaleTimeString() : '—'}</strong>
            </span>
            <span>
              Completed: <strong className="text-slate-200">{execution.completed_at ? new Date(execution.completed_at).toLocaleTimeString() : '—'}</strong>
            </span>
            <span className="flex items-center gap-1 text-cyan-300 font-mono">
              <Timer className="w-3.5 h-3.5" /> Duration: {computeTotalDuration()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {getHeaderStatusBadge(execution.status)}
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

      {/* RULE 8 HUMAN APPROVAL BANNER WITH FULL RESOLVED PAYLOAD INSPECTION */}
      {execution.status === 'waiting_approval' && (
        <div className="rounded-2xl p-6 bg-gradient-to-r from-amber-950/80 via-slate-900 to-slate-900 border-2 border-amber-500 shadow-2xl shadow-amber-500/10 space-y-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center shrink-0 text-amber-400">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  RULE 8 HUMAN-IN-THE-LOOP APPROVAL REQUIRED
                </span>
                <span className="text-xs text-amber-400 font-mono">
                  Pending Step: '{execution.pending_approval_step}'
                </span>
              </div>
              <h3 className="text-lg font-bold text-white mt-1">
                Authorization Required Before Performing {approvalDetails?.method || 'Mutating'} Operation
              </h3>
              <p className="text-xs text-slate-300 mt-1">
                Review the resolved API endpoint, HTTP method, request body, and workflow execution plan below before authorizing.
              </p>
            </div>
          </div>

          {approvalDetails && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 bg-slate-950/80 p-4 rounded-xl border border-amber-500/30 text-xs">
              <div className="space-y-2">
                <div>
                  <span className="text-slate-400 block mb-0.5 font-semibold">API Endpoint & Method:</span>
                  <div className="font-mono text-white bg-slate-900 px-3 py-1.5 rounded border border-slate-800 break-all">
                    <span className="text-amber-400 font-bold mr-2">{approvalDetails.method}</span>
                    {approvalDetails.endpoint}
                  </div>
                </div>
                {approvalDetails.transferred_variables && Object.keys(approvalDetails.transferred_variables).length > 0 && (
                  <div>
                    <span className="text-slate-400 block mb-0.5 font-semibold">Transferred Variables:</span>
                    <pre className="p-2.5 rounded bg-slate-900 border border-slate-800 text-[11px] font-mono text-cyan-300 overflow-x-auto">
                      {JSON.stringify(approvalDetails.transferred_variables, null, 2)}
                    </pre>
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <div>
                  <span className="text-slate-400 block mb-0.5 font-semibold">Resolved Request Body / Data Being Modified:</span>
                  <pre className="p-2.5 rounded bg-slate-900 border border-slate-800 text-[11px] font-mono text-emerald-300 overflow-x-auto max-h-40">
                    {JSON.stringify(approvalDetails.request_body ?? approvalDetails.data_being_modified ?? {}, null, 2)}
                  </pre>
                </div>
              </div>
            </div>
          )}

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
        <div className="rounded-2xl p-6 bg-gradient-to-r from-rose-950/80 via-slate-900 to-slate-900 border border-rose-500/50 shadow-2xl space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-500/20 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0">
                <XCircle className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-base font-bold text-white">Execution Encountered An Error</h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    {execution.error_details?.category || 'ERROR'}
                  </span>
                </div>
                <p className="text-xs text-rose-300 font-mono">
                  Failed Step '{execution.error_details?.step_id}': {execution.error_details?.message}
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

          {diagnosis && (
            <div className="bg-slate-950/80 rounded-xl p-5 border border-indigo-500/30 space-y-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  AI ROOT CAUSE DIAGNOSIS (qwen2.5:7b-instruct)
                </span>
                <span className="text-[10px] text-amber-400 font-mono">
                  RULE 9: Explicit User Confirmation Required
                </span>
              </div>

              <div>
                <h4 className="text-sm font-bold text-white mb-1">{diagnosis.root_cause}</h4>
                <p className="text-xs text-slate-300 leading-relaxed">{diagnosis.explanation}</p>
              </div>

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

      {/* FINAL WORKFLOW OUTPUT PANEL */}
      {execution.status === 'completed' && execution.final_output !== undefined && execution.final_output !== null && (
        <div className="bg-gradient-to-r from-emerald-950/50 via-slate-900 to-slate-900 border border-emerald-500/40 rounded-2xl p-5 shadow-xl space-y-2">
          <h3 className="text-sm font-bold text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            Final Workflow Output
          </h3>
          <pre className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-emerald-200 overflow-x-auto max-h-64">
            {JSON.stringify(execution.final_output, null, 2)}
          </pre>
        </div>
      )}

      {/* INDIVIDUAL WORKFLOW STEPS TRACE */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Layers className="w-4 h-4 text-indigo-400" />
            Workflow Steps, Resolved Requests & Transferred State
          </h3>
          <div className="flex items-center gap-2 text-[10px] font-mono text-slate-400 flex-wrap">
            <span className="px-1.5 py-0.5 rounded bg-slate-700/40 text-slate-300">Pending</span>
            <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300">Running</span>
            <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">Waiting Approval</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">Completed</span>
            <span className="px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-300">Failed</span>
          </div>
        </div>

        <div className="space-y-4">
          {allStepIds.map((stepId) => {
            const wfNode = nodeMap.get(stepId);
            const res: ExecutionStepResult | undefined = execution.step_results?.[stepId];
            let stepStatus: string = res?.status || 'pending';
            if (!res && execution.pending_approval_step === stepId && execution.status === 'waiting_approval') {
              stepStatus = 'waiting_approval';
            }
            const method = res?.method || wfNode?.data?.method;
            const endpoint = res?.endpoint || wfNode?.data?.path;

            return (
              <div key={stepId} className="bg-slate-950 rounded-xl border border-slate-800 p-4 space-y-3">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="font-mono text-xs font-bold text-indigo-300">{stepId}</span>
                    {wfNode?.data?.label && (
                      <span className="text-xs font-medium text-white">{wfNode.data.label}</span>
                    )}
                    {getStepColorBadge(stepStatus)}
                    {res?.error_category && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-500/20 text-rose-300 border border-rose-500/30">
                        {res.error_category}
                      </span>
                    )}
                  </div>

                  <div className="text-[11px] font-mono text-slate-400 flex items-center gap-3">
                    {res?.status_code && <span>HTTP {res.status_code}</span>}
                    {res?.attempts && res.attempts > 1 && <span>Attempts: {res.attempts}</span>}
                    {res?.elapsed_ms !== undefined && <span>{res.elapsed_ms}ms</span>}
                  </div>
                </div>

                {method && endpoint && (
                  <div className="text-[11px] font-mono text-slate-300 bg-slate-900 px-3 py-1.5 rounded border border-slate-800 break-all">
                    <span className="text-cyan-400 font-bold mr-2">{method}</span>
                    {endpoint}
                  </div>
                )}

                {res?.transferred_variables && Object.keys(res.transferred_variables).length > 0 && (
                  <div>
                    <span className="text-[11px] font-semibold text-slate-400 flex items-center gap-1 mb-1">
                      <ArrowRight className="w-3 h-3 text-cyan-400" /> Transferred Variables (Resolved):
                    </span>
                    <pre className="p-2.5 rounded-lg bg-slate-900 text-[11px] font-mono text-cyan-300 overflow-x-auto">
                      {JSON.stringify(res.transferred_variables, null, 2)}
                    </pre>
                  </div>
                )}

                {res?.request && (res.request.params && Object.keys(res.request.params).length > 0 || res.request.body !== null && res.request.body !== undefined) && (
                  <div>
                    <span className="text-[11px] font-semibold text-slate-400 block mb-1">
                      Resolved Request Parameters & Body:
                    </span>
                    <pre className="p-2.5 rounded-lg bg-slate-900 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-40">
                      {JSON.stringify(
                        {
                          ...(res.request.params && Object.keys(res.request.params).length > 0 ? { query_params: res.request.params } : {}),
                          ...(res.request.body !== null && res.request.body !== undefined ? { body: res.request.body } : {}),
                        },
                        null,
                        2
                      )}
                    </pre>
                  </div>
                )}

                {res?.transformation_result !== undefined && (
                  <div>
                    <span className="text-[11px] font-semibold text-slate-400 block mb-1">
                      Transformation Result:
                    </span>
                    <pre className="p-2.5 rounded-lg bg-slate-900 text-[11px] font-mono text-emerald-300 overflow-x-auto">
                      {JSON.stringify(res.transformation_result, null, 2)}
                    </pre>
                  </div>
                )}

                {res?.output !== undefined && res?.step_type !== 'transform' && (
                  <div>
                    <span className="text-[11px] font-semibold text-slate-400 block mb-1">
                      API Response Output:
                    </span>
                    <pre className="p-2.5 rounded-lg bg-slate-900 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-48">
                      {JSON.stringify(res.output, null, 2)}
                    </pre>
                  </div>
                )}

                {res?.error && (
                  <div className="p-2.5 rounded-lg bg-rose-950/40 border border-rose-500/30 text-xs font-mono text-rose-300">
                    {res.error}
                  </div>
                )}

                {res?.reason && (
                  <div className="text-xs text-slate-400 italic">Reason: {res.reason}</div>
                )}
              </div>
            );
          })}

          {allStepIds.length === 0 && (
            <div className="py-6 text-center text-xs text-slate-500">
              No steps found for this workflow.
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
