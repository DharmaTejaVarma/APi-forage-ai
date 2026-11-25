/**
 * APIForge AI Frontend TypeScript Types
 */

export interface User {
  id: number;
  email: string;
  role: 'user' | 'admin';
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface APIConnection {
  id: number;
  name: string;
  description?: string;
  base_url: string;
  auth_type: 'none' | 'bearer' | 'api_key' | 'basic';
  encrypted_credentials?: string;
  default_headers?: Record<string, string>;
  created_at: string;
  endpoints_count?: number;
}

export interface Endpoint {
  id: number;
  connection_id: number;
  path: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  summary?: string;
  description?: string;
  parameters?: Array<{
    name: string;
    in: 'query' | 'path' | 'header' | 'body';
    required?: boolean;
    schema?: any;
    description?: string;
  }>;
  request_body_schema?: Record<string, any>;
  response_schema?: Record<string, any>;
  security?: Array<Record<string, any>>;
  embedding?: number[];
  has_embedding?: boolean;
  created_at: string;
}

export interface WorkflowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label: string;
    step_id?: string;
    method?: string;
    path?: string;
    connection_id?: number;
    endpoint_id?: number;
    parameters?: Record<string, any>;
    headers?: Record<string, any>;
    request_body?: Record<string, any>;
    transformation?: {
      operation?: string;
      formula?: string;
      inputs?: Record<string, any>;
      [key: string]: any;
    };
    condition?: any;
    when?: string;
    output_var?: string;
    error_handling?: Record<string, any>;
    requires_approval?: boolean;
    step_type?: string;
    status?: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'skipped';
    output?: any;
    error?: string;
  };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  animated?: boolean;
}

export interface Workflow {
  id: number;
  user_id: number;
  title: string;
  description?: string;
  raw_prompt?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  dag_structure?: Record<string, any>;
  status: 'draft' | 'active' | 'archived';
  is_shared: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExecutionStepResult {
  step_id?: string;
  label?: string;
  step_type?: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'skipped';
  method?: string;
  endpoint?: string;
  request?: {
    method: string;
    url: string;
    headers?: Record<string, any>;
    params?: Record<string, any>;
    body?: any;
  };
  transferred_variables?: Record<string, any>;
  transformation_result?: any;
  condition_result?: boolean;
  status_code?: number;
  output?: any;
  elapsed_ms?: number;
  attempts?: number;
  error?: string;
  error_category?: string;
  reason?: string;
}

export interface ExecutionLog {
  timestamp: string;
  step_id?: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  message: string;
}

export interface CandidateFix {
  fix_id: string;
  title: string;
  description: string;
  target_node_id: string;
  change_type: string;
  patch: Record<string, any>;
}

export interface ErrorDiagnosis {
  step_id: string;
  error_category: string;
  root_cause: string;
  explanation: string;
  candidate_fixes: CandidateFix[];
  requires_user_approval: boolean;
}

export interface PendingApprovalDetails {
  step_id: string;
  label?: string;
  method?: string;
  endpoint?: string;
  headers?: Record<string, any>;
  parameters?: Record<string, any>;
  request_body?: any;
  data_being_modified?: any;
  transferred_variables?: Record<string, any>;
  workflow_plan?: Array<{
    step_id: string;
    label?: string;
    method?: string;
    path?: string;
    status: string;
  }>;
}

export interface WorkflowExecution {
  id: number;
  workflow_id: number;
  user_id: number;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';
  step_results?: Record<string, ExecutionStepResult>;
  execution_logs?: ExecutionLog[];
  requires_approval: boolean;
  pending_approval_step?: string;
  approved_steps?: string[];
  pending_approval_details?: PendingApprovalDetails;
  approval_status: 'not_required' | 'pending' | 'approved' | 'rejected';
  final_output?: any;
  error_details?: {
    step_id?: string;
    category?: string;
    summary?: string;
    message?: string;
    status_code?: number;
    response_body?: any;
    ai_diagnosis?: ErrorDiagnosis;
  };
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface DashboardSummary {
  total_workflows: number;
  total_executions: number;
  completed_executions: number;
  failed_executions: number;
  waiting_approval: number;
  success_rate: number;
  total_connections: number;
  total_endpoints: number;
  recent_executions: Array<{
    id: number;
    workflow_id: number;
    workflow_title: string;
    status: string;
    requires_approval: boolean;
    approval_status: string;
    created_at: string;
    completed_at?: string;
  }>;
}

export interface AuditLog {
  id: number;
  user_id?: number;
  action: string;
  resource_type?: string;
  resource_id?: string;
  details?: Record<string, any>;
  ip_address?: string;
  created_at: string;
}
