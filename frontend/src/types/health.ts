export interface ServiceStatus {
  status: string;
  [key: string]: any;
}

export interface ModelDetail {
  name: string;
  available: boolean;
  fallback_available?: boolean;
  fallback_name?: string;
}

export interface OllamaStatus {
  status: string;
  url: string;
  connected: boolean;
  error?: string;
  models: {
    chat_model: ModelDetail;
    embed_model: ModelDetail;
  };
  available_models?: string[];
}

export interface DatabaseStatus {
  status: string;
  dialect: string;
  connected: boolean;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'error';
  version: string;
  timestamp: string;
  services: {
    backend: ServiceStatus;
    database: DatabaseStatus;
    ollama: OllamaStatus;
  };
}
