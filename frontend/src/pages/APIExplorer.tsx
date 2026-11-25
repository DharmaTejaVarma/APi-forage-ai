import React, { useEffect, useState } from 'react';
import { Search, Sparkles, CheckCircle2, Globe } from 'lucide-react';
import { api } from '../api/client';
import { Endpoint, APIConnection } from '../types';

export const APIExplorer: React.FC = () => {
  const [connections, setConnections] = useState<APIConnection[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [selectedConnection, setSelectedConnection] = useState<number | 'all'>('all');
  const [semanticQuery, setSemanticQuery] = useState('');
  const [semanticResults, setSemanticResults] = useState<Array<{ endpoint: Endpoint; similarity_score: number }> | null>(null);
  const [searching, setSearching] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    async function loadInitial() {
      try {
        const conns = await api.getConnections();
        setConnections(conns);
        const eps = await api.getEndpoints();
        setEndpoints(eps);
      } catch (err) {
        console.error('Failed to load explorer data:', err);
      }
    }
    loadInitial();
  }, []);

  const handleConnectionChange = async (id: number | 'all') => {
    setSelectedConnection(id);
    setSemanticResults(null);
    try {
      const eps = await api.getEndpoints(id === 'all' ? undefined : id);
      setEndpoints(eps);
    } catch (err) {
      console.error(err);
    }
  };

  const handleSemanticSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!semanticQuery.trim()) {
      setSemanticResults(null);
      return;
    }
    setSearching(true);
    try {
      const results = await api.searchSemantic(
        semanticQuery,
        selectedConnection === 'all' ? undefined : selectedConnection
      );
      setSemanticResults(results);
    } catch (err) {
      console.error('Semantic search failed:', err);
    } finally {
      setSearching(false);
    }
  };

  const displayList = semanticResults ? semanticResults.map((r) => r.endpoint) : endpoints;

  const methodColors: Record<string, string> = {
    GET: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    POST: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    PUT: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    DELETE: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    PATCH: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Search className="w-5 h-5 text-indigo-400" />
          API Explorer & Semantic Vector Search
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Explore imported OpenAPI endpoints and test cosine-similarity semantic retrieval powered by nomic-embed-text.
        </p>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col md:flex-row gap-3">
        <form onSubmit={handleSemanticSearch} className="flex-1 flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-3" />
            <input
              type="text"
              value={semanticQuery}
              onChange={(e) => setSemanticQuery(e.target.value)}
              placeholder="Semantic natural-language search (e.g. 'find product details with price and stock')"
              className="w-full pl-10 pr-4 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>
          <button
            type="submit"
            disabled={searching}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium flex items-center gap-1.5 shadow-lg shadow-indigo-600/20 transition-all shrink-0"
          >
            <Sparkles className="w-3.5 h-3.5" />
            {searching ? 'Searching...' : 'Semantic Search'}
          </button>
        </form>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-400 font-medium">Filter API:</span>
          <select
            value={selectedConnection}
            onChange={(e) => handleConnectionChange(e.target.value === 'all' ? 'all' : Number(e.target.value))}
            className="px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-indigo-500"
          >
            <option value="all">All Connections ({endpoints.length} Endpoints)</option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Semantic Results Banner */}
      {semanticResults && (
        <div className="flex items-center justify-between p-3 rounded-xl bg-indigo-950/40 border border-indigo-500/30 text-xs text-indigo-300">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span>
              Found {semanticResults.length} matching endpoints using cosine similarity for: "{semanticQuery}"
            </span>
          </div>
          <button
            onClick={() => {
              setSemanticResults(null);
              setSemanticQuery('');
            }}
            className="text-slate-400 hover:text-white underline text-[11px]"
          >
            Clear Search
          </button>
        </div>
      )}

      {/* Endpoints List */}
      <div className="space-y-3">
        {displayList.map((ep) => {
          const isExpanded = expandedId === ep.id;
          const matchInfo = semanticResults?.find((r) => r.endpoint.id === ep.id);

          return (
            <div
              key={ep.id}
              className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden hover:border-slate-700 transition-all shadow-md"
            >
              <div
                onClick={() => setExpandedId(isExpanded ? null : ep.id)}
                className="p-4 flex items-center justify-between cursor-pointer select-none"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span
                    className={`px-2.5 py-1 rounded-md text-[11px] font-mono font-bold border ${
                      methodColors[ep.method] || 'bg-slate-800 text-slate-300'
                    }`}
                  >
                    {ep.method}
                  </span>
                  <span className="font-mono text-xs text-white font-medium truncate">{ep.path}</span>
                  <span className="text-xs text-slate-400 truncate hidden md:inline">
                    — {ep.summary || ep.description || 'No summary'}
                  </span>
                </div>

                <div className="flex items-center gap-3 shrink-0 text-xs">
                  {ep.security && ep.security.length > 0 && (
                    <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono text-[10px]">
                      Auth Required
                    </span>
                  )}
                  {matchInfo && (
                    <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-mono text-[10px]">
                      {(matchInfo.similarity_score * 100).toFixed(1)}% Match
                    </span>
                  )}
                  {(ep.has_embedding || ep.embedding) ? (
                    <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
                      <CheckCircle2 className="w-3 h-3" /> Vectorized
                    </span>
                  ) : (
                    <span className="text-[10px] text-slate-500 font-mono">Unembedded</span>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="p-4 bg-slate-950/70 border-t border-slate-800 space-y-3 text-xs">
                  {ep.description && (
                    <div>
                      <span className="text-slate-400 font-semibold block mb-0.5">Description:</span>
                      <p className="text-slate-300">{ep.description}</p>
                    </div>
                  )}

                  {ep.parameters && ep.parameters.length > 0 && (
                    <div>
                      <span className="text-slate-400 font-semibold block mb-1.5">Parameters:</span>
                      <div className="overflow-x-auto">
                        <table className="w-full text-left font-mono text-[11px]">
                          <thead className="text-slate-500 border-b border-slate-800">
                            <tr>
                              <th className="py-1 px-2">Name</th>
                              <th className="py-1 px-2">In</th>
                              <th className="py-1 px-2">Required</th>
                              <th className="py-1 px-2">Description</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-800/40 text-slate-300">
                            {ep.parameters.map((p, i) => (
                              <tr key={i}>
                                <td className="py-1 px-2 text-indigo-400">{p.name}</td>
                                <td className="py-1 px-2 text-slate-400">{p.in}</td>
                                <td className="py-1 px-2">{p.required ? 'Yes' : 'No'}</td>
                                <td className="py-1 px-2 text-slate-400">{p.description || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {ep.request_body_schema && (
                    <div>
                      <span className="text-slate-400 font-semibold block mb-1">Request Body Schema:</span>
                      <pre className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-[10px] text-slate-300 overflow-x-auto">
                        {JSON.stringify(ep.request_body_schema, null, 2)}
                      </pre>
                    </div>
                  )}

                  {ep.response_schema && (
                    <div>
                      <span className="text-slate-400 font-semibold block mb-1">Response Schema:</span>
                      <pre className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-[10px] text-slate-300 overflow-x-auto">
                        {JSON.stringify(ep.response_schema, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {displayList.length === 0 && (
          <div className="p-12 text-center bg-slate-900/50 rounded-xl border border-dashed border-slate-800">
            <Globe className="w-8 h-8 text-slate-600 mx-auto mb-2" />
            <p className="text-xs text-slate-400">No endpoints found matching current query or connection filter.</p>
          </div>
        )}
      </div>
    </div>
  );
};
