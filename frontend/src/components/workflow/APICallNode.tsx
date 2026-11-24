import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { ShieldAlert, Globe, CheckCircle2, Clock, XCircle, PauseCircle } from 'lucide-react';

interface APICallNodeProps {
  data: {
    label: string;
    method?: string;
    path?: string;
    requires_approval?: boolean;
    status?: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed';
    output?: any;
    elapsed_ms?: number;
  };
}

const methodColors: Record<string, { bg: string; text: string; border: string }> = {
  GET: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
  POST: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  PUT: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/30' },
  DELETE: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' },
  PATCH: { bg: 'bg-purple-500/10', text: 'text-purple-400', border: 'border-purple-500/30' },
};

export const APICallNode: React.FC<APICallNodeProps> = ({ data }) => {
  const method = (data.method || 'GET').toUpperCase();
  const colors = methodColors[method] || methodColors.GET;

  const statusIcons = {
    pending: <Clock className="w-3.5 h-3.5 text-slate-400" />,
    running: <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />,
    waiting_approval: <PauseCircle className="w-3.5 h-3.5 text-amber-400 animate-pulse" />,
    completed: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
    failed: <XCircle className="w-3.5 h-3.5 text-rose-400" />,
  };

  return (
    <div
      className={`min-w-[240px] max-w-[320px] rounded-xl bg-slate-900 border ${
        data.status === 'waiting_approval'
          ? 'border-amber-500 shadow-lg shadow-amber-500/20'
          : data.status === 'completed'
          ? 'border-emerald-500/50'
          : data.status === 'failed'
          ? 'border-rose-500/50'
          : 'border-slate-800 hover:border-slate-700'
      } p-3.5 shadow-xl transition-all`}
    >
      <Handle type="target" position={Position.Left} className="w-3 h-3 !bg-indigo-500" />

      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5">
          <span
            className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold uppercase ${colors.bg} ${colors.text} border ${colors.border}`}
          >
            {method}
          </span>
          {data.requires_approval && (
            <span
              className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-medium"
              title="Rule 8: Requires explicit human approval before execution"
            >
              <ShieldAlert className="w-3 h-3" />
              Approval
            </span>
          )}
        </div>

        {data.status && (
          <div className="flex items-center gap-1 text-[11px] font-mono capitalize text-slate-300">
            {statusIcons[data.status]}
          </div>
        )}
      </div>

      <div className="font-medium text-xs text-slate-200 mb-1 truncate" title={data.label}>
        {data.label}
      </div>

      <div className="flex items-center gap-1 font-mono text-[11px] text-slate-400 truncate bg-slate-950/60 px-2 py-1 rounded border border-slate-800/80">
        <Globe className="w-3 h-3 text-slate-400 shrink-0" />
        <span className="truncate">{data.path || '/'}</span>
      </div>

      {data.elapsed_ms !== undefined && (
        <div className="mt-2 text-[10px] text-slate-400 text-right font-mono">
          {data.elapsed_ms}ms
        </div>
      )}

      <Handle type="source" position={Position.Right} className="w-3 h-3 !bg-indigo-500" />
    </div>
  );
};
