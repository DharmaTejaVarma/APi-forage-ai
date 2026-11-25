import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Sparkles,
  GitFork,
  Play,
  CheckCircle2,
  AlertCircle,
  ShieldAlert,
  Layers,
  Cpu,
  Bot,
  Zap,
  Timer,
} from 'lucide-react';
import { api } from '../api/client';
import { Workflow } from '../types';

export const Generator: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const PROMPT_EMAIL =
    'Fetch product 3, extract its title, and send an email containing the product title using the email API.';
  const PROMPT_DISCOUNT =
    'Fetch product 5, calculate a 10% discount using SimpleEval, and create an order with the discounted price.';

  const [prompt, setPrompt] = useState(
    searchParams.get('demo') === 'true' ? PROMPT_DISCOUNT : PROMPT_EMAIL
  );
  const [mode, setMode] = useState<'multi_agent' | 'single'>('multi_agent');
  const [engine, setEngine] = useState<'fast' | 'ollama_3b' | 'ollama'>('fast');
  const [generating, setGenerating] = useState(false);
  const [generatedWorkflow, setGeneratedWorkflow] = useState<Workflow | null>(null);
  const [generationTimeMs, setGenerationTimeMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (searchParams.get('demo') === 'true') {
      setPrompt(PROMPT_DISCOUNT);
    }
  }, [searchParams]);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setError(null);
    setGenerating(true);
    setGeneratedWorkflow(null);
    setGenerationTimeMs(null);
    const start = performance.now();

    try {
      let wf: Workflow;
      if (mode === 'multi_agent') {
        wf = await api.generateWorkflowMultiAgent(prompt, engine);
      } else {
        wf = await api.generateWorkflow(prompt, engine);
      }
      setGenerationTimeMs(Math.round(performance.now() - start));
      setGeneratedWorkflow(wf);
    } catch (err: any) {
      setError(err.message || 'Workflow generation failed.');
    } finally {
      setGenerating(false);
    }
  };

  const handleExecuteNow = async () => {
    if (!generatedWorkflow) return;
    try {
      const exec = await api.executeWorkflow(generatedWorkflow.id, false);
      navigate(`/executions/${exec.id}`);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const agentTrace = generatedWorkflow?.dag_structure?.agent_trace as
    | Array<{
        agent: string;
        status: string;
        details: string;
        duration_ms?: number;
        inputs?: Record<string, any>;
        outputs?: Record<string, any>;
        errors?: string | null;
      }>
    | undefined;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-400" />
          Autonomous AI Workflow Generator
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Instruct local Ollama (qwen2.5:7b-instruct + nomic-embed-text) using your registered OpenAPI specifications to build validated DAG workflows.
        </p>
      </div>

      {/* Generator Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
        <form onSubmit={handleGenerate} className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold text-slate-300">
                Natural-Language Instruction:
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setMode('multi_agent')}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                    mode === 'multi_agent'
                      ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shadow-sm shadow-indigo-500/10'
                      : 'bg-slate-800/80 text-slate-400 border border-slate-700/80 hover:text-slate-300'
                  }`}
                >
                  <Layers className="w-3.5 h-3.5 text-indigo-400" />
                  Multi-Agent (LangGraph 7 Agents)
                </button>
                <button
                  type="button"
                  onClick={() => setMode('single')}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                    mode === 'single'
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-500/10'
                      : 'bg-slate-800/80 text-slate-400 border border-slate-700/80 hover:text-slate-300'
                  }`}
                >
                  <Zap className="w-3.5 h-3.5 text-cyan-400" />
                  Single-Prompt (Ollama)
                </button>
              </div>
            </div>

            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder="e.g. Fetch product 3, extract its title, and send an email containing the product title using the email API."
              className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition-colors shadow-inner"
            />

            {/* Quick Prompt Suggestions */}
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <span className="text-[11px] text-slate-500 font-medium">Quick Presets:</span>
              <button
                type="button"
                onClick={() => setPrompt(PROMPT_EMAIL)}
                className="text-[11px] px-2.5 py-1 rounded-md bg-slate-800/60 hover:bg-slate-800 text-slate-300 border border-slate-700/60 transition-colors"
              >
                📧 Product 3 Title → Email API
              </button>
              <button
                type="button"
                onClick={() => setPrompt(PROMPT_DISCOUNT)}
                className="text-[11px] px-2.5 py-1 rounded-md bg-slate-800/60 hover:bg-slate-800 text-slate-300 border border-slate-700/60 transition-colors"
              >
                🏷️ Product 5 → 10% Discount → Create Order
              </button>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <div className="flex items-center rounded-lg bg-slate-950 border border-slate-800 p-0.5 gap-0.5">
                <button
                  type="button"
                  onClick={() => setEngine('fast')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    engine === 'fast'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Zap className="w-3 h-3 text-emerald-400" />
                  Fast AI (1-2s)
                </button>
                <button
                  type="button"
                  onClick={() => setEngine('ollama_3b')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    engine === 'ollama_3b'
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Bot className="w-3 h-3 text-cyan-400" />
                  Ollama 3B (~30s)
                </button>
                <button
                  type="button"
                  onClick={() => setEngine('ollama')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    engine === 'ollama'
                      ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Bot className="w-3 h-3 text-indigo-400" />
                  Ollama 7B (Deep)
                </button>
              </div>
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-slate-300 text-[11px]">
                <Cpu className="w-3.5 h-3.5 text-cyan-400" />
                nomic-embed-text
              </span>
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 font-mono text-[11px]">
                <Layers className="w-3 h-3 text-indigo-400" /> Local AI Only
              </span>
            </div>

            <button
              type="submit"
              disabled={generating || !prompt.trim()}
              className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-600 hover:to-cyan-600 text-white font-medium text-xs shadow-lg shadow-indigo-500/25 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <Sparkles className="w-4 h-4" />
              {generating ? 'Orchestrating Plan...' : 'Generate Workflow Plan'}
            </button>
          </div>
        </form>

        {error && (
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start gap-2.5 text-xs text-rose-300">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {generating && (
          <div className="p-6 rounded-xl bg-slate-950/70 border border-slate-800 text-center space-y-3 animate-pulse">
            <div className="w-10 h-10 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin mx-auto" />
            <div className="text-sm font-semibold text-white">
              {mode === 'multi_agent'
                ? 'LangGraph 7-Agent Orchestration in Progress...'
                : 'Single-Pass DAG Generation in Progress...'}
            </div>
            <p className="text-xs text-slate-400 max-w-md mx-auto">
              {engine === 'fast'
                ? 'Running Intent → Semantic Discovery (nomic-embed-text) → Schema Analysis → Fast Semantic Planner → Data Mapping → Validation (~1-2s).'
                : `Running local Ollama (${engine === 'ollama_3b' ? 'qwen2.5:3b' : 'qwen2.5:7b-instruct'}) + nomic-embed-text → Validation → Supervisor.`}
            </p>
          </div>
        )}
      </div>

      {/* Generated Workflow Plan Preview */}
      {generatedWorkflow && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-6 animate-in fade-in duration-300">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
            <div>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  DAG PLAN GENERATED
                </span>
                {generationTimeMs !== null && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                    <Timer className="w-3 h-3 text-cyan-400" />
                    {(generationTimeMs / 1000).toFixed(2)}s
                  </span>
                )}
                <span className="text-xs text-slate-400 font-mono">ID: #{generatedWorkflow.id}</span>
              </div>
              <h3 className="text-lg font-bold text-white">{generatedWorkflow.title}</h3>
              <p className="text-xs text-slate-400">{generatedWorkflow.description}</p>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => navigate(`/builder?id=${generatedWorkflow.id}`)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors flex items-center gap-1.5"
              >
                <GitFork className="w-3.5 h-3.5 text-cyan-400" />
                Open in Visual Builder
              </button>
              <button
                onClick={handleExecuteNow}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium shadow-lg shadow-emerald-600/20 transition-all flex items-center gap-1.5"
              >
                <Play className="w-3.5 h-3.5" />
                Execute DAG Workflow
              </button>
            </div>
          </div>

          {/* Agent Trace Log */}
          {agentTrace && agentTrace.length > 0 && (
            <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800 space-y-2">
              <div className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                Multi-Agent Execution Trace:
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px] font-mono">
                {agentTrace.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded bg-slate-900 border border-slate-800/80 flex items-start justify-between gap-2"
                  >
                    <div className="flex items-start gap-2 min-w-0">
                      <CheckCircle2 className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${item.status === 'failed' ? 'text-rose-400' : item.status === 'retrying' ? 'text-amber-400' : 'text-emerald-400'}`} />
                      <div className="min-w-0">
                        <span className="text-indigo-300 font-semibold">{item.agent}:</span>{' '}
                        <span className="text-slate-400">{item.details}</span>
                      </div>
                    </div>
                    {item.duration_ms !== undefined && (
                      <span className="text-[10px] text-slate-500 shrink-0">{item.duration_ms}ms</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Nodes Preview */}
          <div className="space-y-3">
            <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Topological Step Sequence ({generatedWorkflow.nodes.length} Nodes)
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {generatedWorkflow.nodes.map((node, i) => {
                const d = node.data;

                return (
                  <div
                    key={node.id}
                    className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2 flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span className="font-mono text-[10px] text-slate-500">#{i + 1} {node.id}</span>
                        {d.requires_approval && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-medium">
                            <ShieldAlert className="w-3 h-3" /> Approval
                          </span>
                        )}
                      </div>
                      <div className="font-semibold text-xs text-white truncate">{d.label}</div>
                      {d.method && (
                        <div className="mt-1 font-mono text-[11px] text-slate-400 truncate">
                          <span className="text-cyan-400 font-bold">{d.method}</span> {d.path}
                        </div>
                      )}
                      {d.transformation && (
                        <div className="mt-1 font-mono text-[11px] text-cyan-300 bg-slate-900 px-2 py-1 rounded border border-slate-800 truncate">
                          formula: {d.transformation.formula}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
