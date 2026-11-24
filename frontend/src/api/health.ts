import { HealthResponse } from '../types/health';

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/health', {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Server returned HTTP ${response.status}: ${response.statusText}`);
  }

  return response.json();
}
