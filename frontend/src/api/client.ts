/**
 * APIForge AI HTTP API Client
 */
import {
  User,
  AuthResponse,
  APIConnection,
  Endpoint,
  Workflow,
  WorkflowExecution,
  ErrorDiagnosis,
  DashboardSummary,
  AuditLog,
} from '../types';

const BASE_URL = '/api';

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('apiforge_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeader(),
    ...(options.headers || {}),
  };

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMsg = `HTTP Error ${response.status}: ${response.statusText}`;
    try {
      const errData = await response.json();
      errorMsg = errData.detail || errData.message || errorMsg;
    } catch {
      // fallback to status text
    }
    throw new Error(errorMsg);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export const api = {
  // Authentication
  login: (email: string, password: string): Promise<AuthResponse> =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  register: (data: { email: string; password: string; role?: string }) =>
    request<User>('/auth/register', { method: 'POST', body: JSON.stringify(data) }),

  getMe: () => request<User>('/auth/me'),

  // Connections
  getConnections: () => request<APIConnection[]>('/connections'),
  getConnection: (id: number) => request<APIConnection>(`/connections/${id}`),
  createConnection: (data: any) =>
    request<APIConnection>('/connections', { method: 'POST', body: JSON.stringify(data) }),
  deleteConnection: (id: number) =>
    request<{ message: string }>(`/connections/${id}`, { method: 'DELETE' }),
  embedAllConnection: (id: number) =>
    request<{ message: string; embedded_count: number }>(`/connections/${id}/embed-all`, { method: 'POST' }),
  importOpenAPI: (connectionId: number, spec: any) =>
    request<{ message: string; endpoints_imported: number }>(`/connections/${connectionId}/import-openapi`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  // Endpoints
  getEndpoints: (connectionId?: number) =>
    request<Endpoint[]>(connectionId ? `/endpoints?connection_id=${connectionId}` : '/endpoints'),
  searchSemantic: (query: string, connectionId?: number) =>
    request<{ results: Array<{ endpoint: Endpoint; similarity: number }> }>(
      `/endpoints/search/semantic?query=${encodeURIComponent(query)}${
        connectionId ? `&connection_id=${connectionId}` : ''
      }`
    ),

  // Workflows
  getWorkflows: () => request<Workflow[]>('/workflows'),
  getWorkflow: (id: number) => request<Workflow>(`/workflows/${id}`),
  createWorkflow: (data: Partial<Workflow>) =>
    request<Workflow>('/workflows', { method: 'POST', body: JSON.stringify(data) }),
  updateWorkflow: (id: number, data: Partial<Workflow>) =>
    request<Workflow>(`/workflows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteWorkflow: (id: number) =>
    request<{ message: string }>(`/workflows/${id}`, { method: 'DELETE' }),

  generateWorkflow: (prompt: string) =>
    request<Workflow>('/workflows/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),

  generateWorkflowMultiAgent: (prompt: string) =>
    request<Workflow>('/workflows/generate-multi-agent', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),

  // Executions
  executeWorkflow: (workflowId: number) =>
    request<WorkflowExecution>(`/workflows/${workflowId}/execute`, { method: 'POST' }),
  getExecution: (id: number) => request<WorkflowExecution>(`/executions/${id}`),
  getWorkflowExecutions: (workflowId: number) =>
    request<WorkflowExecution[]>(`/workflows/${workflowId}/executions`),
  approveExecution: (id: number) =>
    request<WorkflowExecution>(`/executions/${id}/approve`, { method: 'POST' }),
  rejectExecution: (id: number) =>
    request<WorkflowExecution>(`/executions/${id}/reject`, { method: 'POST' }),
  diagnoseExecution: (id: number) =>
    request<ErrorDiagnosis>(`/executions/${id}/diagnose`, { method: 'POST' }),
  applyFix: (id: number, targetNodeId: string, patch: Record<string, any>, resume = true) =>
    request<WorkflowExecution>(`/executions/${id}/apply-fix`, {
      method: 'POST',
      body: JSON.stringify({ target_node_id: targetNodeId, patch, resume }),
    }),

  // Dashboard & Admin
  getDashboardSummary: () => request<DashboardSummary>('/dashboard/summary'),
  getAdminStats: () => request<any>('/admin/stats'),
  getAdminAuditLogs: (limit = 50, action?: string) =>
    request<AuditLog[]>(`/admin/audit-logs?limit=${limit}${action ? `&action=${action}` : ''}`),
  getAdminUsers: () => request<User[]>('/admin/users'),
  toggleUserActive: (userId: number) =>
    request<User>(`/admin/users/${userId}/toggle-active`, { method: 'POST' }),
};
