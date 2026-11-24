import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { Calculator, CheckCircle2, Clock, XCircle } from 'lucide-react';

interface TransformNodeProps {
  data: {
    label: string;
    transformation?: {
      formula: string;
      inputs?: Record<string, any>;
    };
    status?: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed';
    output?: any;
  };
}

export const TransformNode: React.FC<TransformNodeProps> = ({ data }) => {
  const formula = data.transformation?.formula || 'N/A';

  return (
    <div
      className={`min-w-[220px] max-w-[300px] rounded-xl bg-slate-900 border ${
        data.status === 'completed'
          ? 'border-emerald-500/50'
          : data.status === 'failed'
          ? 'border-rose-500/50'
          : 'border-cyan-500/30 hover:border-cyan-500/60'
      } p-3.5 shadow-xl transition-all`}
    >
      <Handle type="target" position={Position.Left} className="w-3 h-3 !bg-cyan-500" />

      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
          <Calculator className="w-3 h-3" />
          CALC
        </span>

        {data.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
        {data.status === 'failed' && <XCircle className="w-3.5 h-3.5 text-rose-400" />}
        {(!data.status || data.status === 'pending') && <Clock className="w-3.5 h-3.5 text-slate-400" />}
      </div>

      <div className="font-medium text-xs text-slate-200 mb-1.5 truncate">
        {data.label || 'Data Transform'}
      </div>

      <div className="font-mono text-[11px] text-cyan-300 bg-slate-950/80 px-2 py-1 rounded border border-slate-800 truncate">
        f(x) = {formula}
      </div>

      {data.output !== undefined && (
        <div className="mt-2 text-[10px] text-emerald-400 font-mono truncate">
          Result: {JSON.stringify(data.output)}
        </div>
      )}

      <Handle type="source" position={Position.Right} className="w-3 h-3 !bg-cyan-500" />
    </div>
  );
};
