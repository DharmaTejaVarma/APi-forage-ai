import React, { useEffect, useState } from 'react';
import {
  Network,
  Plus,
  Trash2,
  Upload,
  Cpu,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { api } from '../api/client';
import { APIConnection } from '../types';

export const Connections: React.FC = () => {
  const [connections, setConnections] = useState<APIConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState<number | null>(null);
  const [importJson, setImportJson] = useState('');
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Form state
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [authType, setAuthType] = useState<'none' | 'bearer' | 'api_key' | 'basic'>('none');
  const [credentials, setCredentials] = useState('');

  const loadConnections = async () => {
    try {
      setLoading(true);
      const data = await api.getConnections();
      setConnections(data);
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConnections();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      let credObj = undefined;
      if (credentials) {
        try {
          credObj = JSON.parse(credentials);
        } catch {
          credObj = { token: credentials, api_key: credentials };
        }
      }

      await api.createConnection({
        name,
        base_url: baseUrl,
        auth_type: authType,
        credentials: credObj,
      });

      setFeedback({ type: 'success', message: `Connection '${name}' created successfully!` });
      setShowAddModal(false);
      setName('');
      setBaseUrl('');
      setCredentials('');
      loadConnections();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this connection and all associated endpoints?')) return;
    try {
      await api.deleteConnection(id);
      setFeedback({ type: 'success', message: 'Connection removed successfully.' });
      loadConnections();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  const handleEmbedAll = async (id: number) => {
    try {
      setFeedback({ type: 'success', message: 'Generating Ollama vector embeddings for endpoints...' });
      const res = await api.embedAllConnection(id);
      setFeedback({
        type: 'success',
        message: `Embedded ${res.embedded_count} endpoints using nomic-embed-text!`,
      });
      loadConnections();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  const handleImportOpenAPI = async (connectionId: number) => {
    try {
      const parsed = JSON.parse(importJson);
      const res = await api.importOpenAPI(connectionId, parsed);
      setFeedback({
        type: 'success',
        message: `Successfully imported ${res.endpoints_imported} endpoints from OpenAPI spec!`,
      });
      setShowImportModal(null);
      setImportJson('');
      loadConnections();
    } catch (err: any) {
      setFeedback({ type: 'error', message: `Import failed: ${err.message}` });
    }
  };

  const handleSetupMockStore = async () => {
    try {
      const conn = await api.createConnection({
        name: 'Mock Store API',
        base_url: 'http://127.0.0.1:8000/mock/api/v1',
        auth_type: 'none',
      });
      // Fetch mock OpenAPI spec
      const resp = await fetch('http://127.0.0.1:8000/mock/api/v1/openapi.json');
      const spec = await resp.json();
      await api.importOpenAPI(conn.id, spec);
      await api.embedAllConnection(conn.id);
      setFeedback({
        type: 'success',
        message: 'Mock Store API connected, endpoints imported, and embedded with nomic-embed-text!',
      });
      loadConnections();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Network className="w-5 h-5 text-indigo-400" />
            API Connections
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Manage external and internal REST services, credentials, and OpenAPI specifications.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSetupMockStore}
            className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs text-cyan-300 font-medium border border-slate-700 transition-colors flex items-center gap-1.5"
          >
            <Cpu className="w-3.5 h-3.5" />
            Connect Mock Store
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium shadow-lg shadow-indigo-600/20 transition-all flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" />
            Add Connection
          </button>
        </div>
      </div>

      {feedback && (
        <div
          className={`p-3 rounded-xl flex items-center gap-2.5 text-xs ${
            feedback.type === 'success'
              ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
              : 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
          }`}
        >
          {feedback.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
          )}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Grid of Connections */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {connections.map((conn) => (
          <div
            key={conn.id}
            className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col justify-between hover:border-slate-700 transition-all shadow-xl"
          >
            <div>
              <div className="flex items-start justify-between gap-2 mb-3">
                <div>
                  <h3 className="font-semibold text-white text-sm">{conn.name}</h3>
                  <span className="inline-block mt-1 font-mono text-[10px] px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700">
                    Auth: {conn.auth_type.toUpperCase()}
                  </span>
                </div>
                <button
                  onClick={() => handleDelete(conn.id)}
                  className="p-1.5 text-slate-500 hover:text-rose-400 rounded-lg hover:bg-slate-800 transition-colors"
                  title="Delete Connection"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="text-xs font-mono text-slate-400 bg-slate-950/80 p-2.5 rounded-lg border border-slate-800/80 break-all mb-4">
                {conn.base_url}
              </div>
            </div>

            <div className="space-y-2 pt-3 border-t border-slate-800">
              <div className="flex gap-2">
                <button
                  onClick={() => setShowImportModal(conn.id)}
                  className="flex-1 py-1.5 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors"
                >
                  <Upload className="w-3.5 h-3.5 text-indigo-400" />
                  Import OpenAPI
                </button>

                <button
                  onClick={() => handleEmbedAll(conn.id)}
                  className="py-1.5 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors"
                  title="Generate vector embeddings via nomic-embed-text"
                >
                  <Cpu className="w-3.5 h-3.5" />
                  Embed
                </button>
              </div>
            </div>
          </div>
        ))}

        {connections.length === 0 && !loading && (
          <div className="col-span-full py-12 text-center bg-slate-900/50 rounded-2xl border border-dashed border-slate-800">
            <Network className="w-10 h-10 text-slate-600 mx-auto mb-3" />
            <h4 className="text-sm font-medium text-slate-300 mb-1">No API Connections Configured</h4>
            <p className="text-xs text-slate-500 mb-4">
              Connect your first REST service or import the local mock store to begin generating workflows.
            </p>
            <button
              onClick={handleSetupMockStore}
              className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium shadow-lg shadow-indigo-600/20"
            >
              Connect Mock Store API
            </button>
          </div>
        )}
      </div>

      {/* Add Connection Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white mb-4">Add API Connection</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Connection Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  placeholder="e.g. Stripe API, Inventory Service"
                  className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Base URL</label>
                <input
                  type="url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  required
                  placeholder="https://api.example.com/v1"
                  className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Authentication Type</label>
                <select
                  value={authType}
                  onChange={(e) => setAuthType(e.target.value as any)}
                  className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="none">None / Public</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="api_key">API Key (Header / Query)</option>
                  <option value="basic">Basic Auth (Username / Password)</option>
                </select>
              </div>

              {authType !== 'none' && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Credentials (Token or JSON)
                  </label>
                  <textarea
                    value={credentials}
                    onChange={(e) => setCredentials(e.target.value)}
                    rows={2}
                    placeholder='{"token": "secret_xyz"} or plain string'
                    className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                  />
                  <span className="text-[10px] text-slate-500">
                    Encrypted symmetrically with Fernet key before persisting to database.
                  </span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium transition-colors"
                >
                  Save Connection
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Import OpenAPI Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white mb-2">Import OpenAPI Specification</h3>
            <p className="text-xs text-slate-400 mb-4">
              Paste your OpenAPI 3.0 or Swagger 2.0 JSON specification below. Endpoints, parameters, schemas, and $ref references will be parsed automatically.
            </p>

            <textarea
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              rows={12}
              placeholder='{ "openapi": "3.0.0", "info": { ... }, "paths": { ... } }'
              className="w-full px-3.5 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            />

            <div className="flex justify-end gap-2 pt-4">
              <button
                type="button"
                onClick={() => {
                  setShowImportModal(null);
                  setImportJson('');
                }}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleImportOpenAPI(showImportModal)}
                disabled={!importJson.trim()}
                className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium transition-colors disabled:opacity-50"
              >
                Parse & Import Endpoints
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
