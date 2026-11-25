import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { GitBranch, CheckCircle2, Clock, XCircle } from 'lucide-react';

interface ConditionNodeProps {
  data: {
    label: string;
    condition?: any;
    status?: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'skipped';
    output?: any;
  };
}

export const ConditionNode: React.FC<ConditionNodeProps> = ({ data }) => {
  const condStr =
    typeof data.condition === 'string'
      ? data.condition
      : data.condition
      ? JSON.stringify(data.condition)
      : 'condition';

  return (
    <div
      className={`min-w-[220px] max-w-[300px] rounded-xl bg-slate-900 border ${
        data.status === 'completed'
          ? 'border-emerald-500/50'
          : data.status === 'failed'
          ? 'border-rose-500/50'
          : 'border-amber-500/40 hover:border-amber-500/70'
      } p-3.5 shadow-xl transition-all`}
    >
      <Handle type="target" position={Position.Left} className="w-3 h-3 !bg-amber-500" />

      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">
          <GitBranch className="w-3 h-3" />
          CONDITION
        </span>

        {data.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
        {data.status === 'failed' && <XCircle className="w-3.5 h-3.5 text-rose-400" />}
        {(!data.status || data.status === 'pending') && <Clock className="w-3.5 h-3.5 text-slate-400" />}
      </div>

      <div className="font-medium text-xs text-slate-200 mb-1.5 truncate">
        {data.label || 'Branch Condition'}
      </div>

      <div className="font-mono text-[11px] text-amber-300 bg-slate-950/80 px-2 py-1 rounded border border-slate-800 truncate">
        if ({condStr})
      </div>

      <Handle type="source" position={Position.Right} className="w-3 h-3 !bg-amber-500" />
    </div>
  );
};

