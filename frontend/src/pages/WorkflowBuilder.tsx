import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  Node,
  Edge,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  GitFork,
  Save,
  Play,
  Trash2,
  Download,
  ShieldAlert,
  Calculator,
  Globe,
  Settings2,
} from 'lucide-react';
import { api } from '../api/client';
import { APICallNode } from '../components/workflow/APICallNode';
import { TransformNode } from '../components/workflow/TransformNode';
import { Workflow } from '../types';

const nodeTypes = {
  api_call: APICallNode,
  transform: TransformNode,
};

export const WorkflowBuilder: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const workflowId = searchParams.get('id');

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [title, setTitle] = useState('New Custom Workflow');
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);

  // Initialize or load workflow
  useEffect(() => {
    async function load() {
      if (workflowId) {
        try {
          const wf = await api.getWorkflow(Number(workflowId));
          setWorkflow(wf);
          setTitle(wf.title);
          setNodes(wf.nodes as Node[]);
          setEdges(wf.edges as Edge[]);
        } catch (err) {
          console.error('Failed to load workflow:', err);
        }
      } else {
        // Default Demonstration DAG Nodes
        const demoNodes: Node[] = [
          {
            id: 'step_1',
            type: 'api_call',
            position: { x: 80, y: 150 },
            data: {
              label: 'Fetch Product 5',
              method: 'GET',
              path: '/products/5',
              requires_approval: false,
            },
          },
          {
            id: 'step_2',
            type: 'transform',
            position: { x: 380, y: 150 },
            data: {
              label: 'Calculate 10% Discount',
              transformation: {
                formula: 'price * 0.9',
                inputs: { price: '{{step_1.output.price}}' },
              },
              requires_approval: false,
            },
          },
          {
            id: 'step_3',
            type: 'api_call',
            position: { x: 680, y: 150 },
            data: {
              label: 'Create Order with Discount',
              method: 'POST',
              path: '/orders',
              request_body: {
                product_id: '{{step_1.output.id}}',
                final_price: '{{step_2.output}}',
                quantity: 1,
              },
              requires_approval: true, // Rule 8!
            },
          },
        ];

        const demoEdges: Edge[] = [
          { id: 'e1-2', source: 'step_1', target: 'step_2', animated: true },
          { id: 'e2-3', source: 'step_2', target: 'step_3', animated: true },
        ];

        setTitle('E-Commerce Order & Discount DAG');
        setNodes(demoNodes);
        setEdges(demoEdges);
      }
    }
    load();
  }, [workflowId]);

  const onNodesChange: OnNodesChange = useCallback(
    (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
    []
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    []
  );

  const onConnect: OnConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, animated: true }, eds)),
    []
  );

  const onNodeClick = (_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  };

  const handleAddAPINode = () => {
    const newId = `step_${nodes.length + 1}`;
    const newNode: Node = {
      id: newId,
      type: 'api_call',
      position: { x: 100 + (nodes.length * 50), y: 100 + (nodes.length * 30) },
      data: {
        label: `API Call ${nodes.length + 1}`,
        method: 'GET',
        path: '/products',
        requires_approval: false,
      },
    };
    setNodes((nds) => [...nds, newNode]);
    setSelectedNode(newNode);
  };

  const handleAddTransformNode = () => {
    const newId = `step_${nodes.length + 1}`;
    const newNode: Node = {
      id: newId,
      type: 'transform',
      position: { x: 100 + (nodes.length * 50), y: 100 + (nodes.length * 30) },
      data: {
        label: `Transform ${nodes.length + 1}`,
        transformation: { formula: 'x * 1.0', inputs: {} },
        requires_approval: false,
      },
    };
    setNodes((nds) => [...nds, newNode]);
    setSelectedNode(newNode);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (workflow?.id) {
        await api.updateWorkflow(workflow.id, {
          title,
          nodes: nodes as any,
          edges: edges as any,
        });
        alert('Workflow saved successfully!');
      } else {
        const created = await api.createWorkflow({
          title,
          nodes: nodes as any,
          edges: edges as any,
          status: 'draft',
        });
        setWorkflow(created);
        navigate(`/builder?id=${created.id}`, { replace: true });
        alert('Workflow created successfully!');
      }
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleRun = async () => {
    setRunning(true);
    try {
      let wfId = workflow?.id;
      if (!wfId) {
        // Save first
        const created = await api.createWorkflow({
          title,
          nodes: nodes as any,
          edges: edges as any,
          status: 'draft',
        });
        wfId = created.id;
        setWorkflow(created);
      }
      const exec = await api.executeWorkflow(wfId);
      navigate(`/executions/${exec.id}`);
    } catch (err: any) {
      alert(`Execution failed: ${err.message}`);
    } finally {
      setRunning(false);
    }
  };

  const handleExportJSON = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify({ title, nodes, edges }, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `${title.replace(/\s+/g, '_')}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const updateSelectedNodeData = (key: string, val: any) => {
    if (!selectedNode) return;
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id === selectedNode.id) {
          const updated = {
            ...n,
            data: {
              ...n.data,
              [key]: val,
            },
          };
          setSelectedNode(updated);
          return updated;
        }
        return n;
      })
    );
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col -m-6 bg-slate-950">
      {/* Top Builder Toolbar */}
      <div className="h-14 bg-slate-900 border-b border-slate-800 px-6 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          <GitFork className="w-5 h-5 text-indigo-400" />
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="bg-transparent text-sm font-bold text-white border-b border-transparent hover:border-slate-700 focus:border-indigo-500 focus:outline-none px-1 py-0.5"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleAddAPINode}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 flex items-center gap-1.5 transition-colors"
          >
            <Globe className="w-3.5 h-3.5 text-blue-400" />
            + API Call
          </button>

          <button
            onClick={handleAddTransformNode}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 flex items-center gap-1.5 transition-colors"
          >
            <Calculator className="w-3.5 h-3.5 text-cyan-400" />
            + Transform
          </button>

          <button
            onClick={handleExportJSON}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            title="Export Workflow JSON"
          >
            <Download className="w-4 h-4" />
          </button>

          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-white border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
          >
            <Save className="w-3.5 h-3.5 text-indigo-400" />
            {saving ? 'Saving...' : 'Save'}
          </button>

          <button
            onClick={handleRun}
            disabled={running}
            className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-medium text-white flex items-center gap-1.5 shadow-lg shadow-emerald-600/20 transition-all disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            {running ? 'Launching...' : 'Run Workflow'}
          </button>
        </div>
      </div>

      {/* Main Flow Canvas & Properties Drawer */}
      <div className="flex-1 flex overflow-hidden relative">
        <div className="flex-1 h-full w-full bg-slate-950">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
            className="bg-slate-950"
          >
            <Background color="#1e293b" gap={20} size={1} />
            <Controls className="!bg-slate-900 !border-slate-800 !text-slate-300" />
            <MiniMap
              nodeColor={(n) => (n.type === 'transform' ? '#06b6d4' : '#6366f1')}
              className="!bg-slate-900 !border-slate-800 rounded-xl"
            />
          </ReactFlow>
        </div>

        {/* Selected Node Properties Panel */}
        {selectedNode && (
          <aside className="w-80 bg-slate-900 border-l border-slate-800 p-5 overflow-y-auto space-y-4 shrink-0 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-indigo-400" />
                <h4 className="text-xs font-bold text-white uppercase tracking-wider">Node Inspector</h4>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-slate-500 hover:text-slate-300 text-xs"
              >
                ✕
              </button>
            </div>

            <div className="text-[11px] font-mono text-slate-400">
              Node ID: <span className="text-indigo-400">{selectedNode.id}</span>
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-slate-300 mb-1">Step Label</label>
              <input
                type="text"
                value={(selectedNode.data as any).label || ''}
                onChange={(e) => updateSelectedNodeData('label', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            {selectedNode.type === 'api_call' && (
              <>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-300 mb-1">HTTP Method</label>
                  <select
                    value={(selectedNode.data as any).method || 'GET'}
                    onChange={(e) => updateSelectedNodeData('method', e.target.value)}
                    className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-indigo-500"
                  >
                    <option value="GET">GET</option>
                    <option value="POST">POST (Requires Approval)</option>
                    <option value="PUT">PUT (Requires Approval)</option>
                    <option value="DELETE">DELETE (Requires Approval)</option>
                    <option value="PATCH">PATCH (Requires Approval)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-slate-300 mb-1">Path</label>
                  <input
                    type="text"
                    value={(selectedNode.data as any).path || ''}
                    onChange={(e) => updateSelectedNodeData('path', e.target.value)}
                    placeholder="/products/{id}"
                    className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <ShieldAlert className="w-4 h-4 text-amber-400" />
                    <div>
                      <div className="text-xs font-medium text-white">Require Approval</div>
                      <div className="text-[10px] text-slate-500">Non-negotiable Rule 8</div>
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={(selectedNode.data as any).requires_approval || false}
                    onChange={(e) => updateSelectedNodeData('requires_approval', e.target.checked)}
                    className="w-4 h-4 rounded text-indigo-600 focus:ring-0 focus:outline-none"
                  />
                </div>
              </>
            )}

            {selectedNode.type === 'transform' && (
              <div>
                <label className="block text-[11px] font-semibold text-slate-300 mb-1">
                  SimpleEval Formula (No eval/exec)
                </label>
                <input
                  type="text"
                  value={(selectedNode.data as any).transformation?.formula || ''}
                  onChange={(e) =>
                    updateSelectedNodeData('transformation', {
                      ...((selectedNode.data as any).transformation || {}),
                      formula: e.target.value,
                    })
                  }
                  placeholder="price * 0.9"
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-cyan-300 focus:outline-none focus:border-cyan-500"
                />
              </div>
            )}

            <button
              onClick={() => {
                setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id));
                setEdges((eds) => eds.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id));
                setSelectedNode(null);
              }}
              className="w-full py-2 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete Node
            </button>
          </aside>
        )}
      </div>
    </div>
  );
};
