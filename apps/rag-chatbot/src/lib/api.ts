/**
 * Typed client for the local backend.
 *
 * Every failure becomes an {@link ApiError} carrying the backend's stable
 * `code`, so components branch on a machine-readable value rather than
 * pattern-matching prose. A non-JSON or unreachable response still produces
 * an ApiError with a sensible code, so no caller ever has to handle two
 * different failure shapes.
 */

import type {
  Capabilities,
  ConversationDetail,
  ConversationSummary,
  DocumentDetail,
  DocumentPreview,
  DocumentSummary,
  JobSummary,
  Message,
  RetrievalMode,
  SystemStatus,
  UploadResponse,
} from './types';

const BASE = '/api/v1';

export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;
  readonly correlationId: string | null;

  constructor(
    code: string,
    message: string,
    options: { retryable?: boolean; status?: number; correlationId?: string | null } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.status = options.status ?? 0;
    this.correlationId = options.correlationId ?? null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError('NETWORK_UNREACHABLE', 'Could not reach the local backend. Is it running?', {
      retryable: true,
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    const envelope = parsed as {
      error?: { code?: string; message?: string; retryable?: boolean };
    } | null;
    const detail = envelope?.error;
    throw new ApiError(
      detail?.code ?? `HTTP_${response.status}`,
      detail?.message ?? 'The request failed.',
      {
        retryable: detail?.retryable ?? response.status >= 500,
        status: response.status,
        correlationId: response.headers.get('X-Correlation-ID'),
      },
    );
  }

  return parsed as T;
}

export const api = {
  // --- system ---
  capabilities: () => request<Capabilities>('/capabilities'),
  systemStatus: () => request<SystemStatus>('/system/status'),
  health: () => request<{ status: string; version: string }>('/health'),

  // --- documents ---
  listDocuments: () => request<DocumentSummary[]>('/documents'),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${encodeURIComponent(id)}`),
  previewDocument: (id: string) =>
    request<DocumentPreview>(`/documents/${encodeURIComponent(id)}/preview`),

  uploadDocument: (file: File, parserProfile: string, forceNewVersion = false) => {
    const form = new FormData();
    form.append('file', file);
    form.append('parser_profile', parserProfile);
    form.append('force_new_version', String(forceNewVersion));
    return request<UploadResponse>('/documents', { method: 'POST', body: form });
  },

  reprocessDocument: (id: string, parserProfile?: string) => {
    const query = parserProfile ? `?parser_profile=${encodeURIComponent(parserProfile)}` : '';
    return request<JobSummary>(`/documents/${encodeURIComponent(id)}/reprocess${query}`, {
      method: 'POST',
    });
  },

  deleteDocument: (id: string) =>
    request<{
      document_id: string;
      deleted: boolean;
      chunks_removed: number;
      display_name: string;
    }>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // --- jobs ---
  getJob: (id: string) => request<JobSummary>(`/jobs/${encodeURIComponent(id)}`),
  retryJob: (id: string) =>
    request<JobSummary>(`/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  cancelJob: (id: string) =>
    request<JobSummary>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),

  /** Live progress for one job. Returns the EventSource so the caller can close it. */
  jobEvents: (id: string) => new EventSource(`${BASE}/jobs/${encodeURIComponent(id)}/events`),

  // --- conversations ---
  listConversations: () => request<ConversationSummary[]>('/conversations'),
  getConversation: (id: string) =>
    request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),

  createConversation: (payload: {
    title?: string;
    selected_document_ids?: string[];
    retrieval_mode?: RetrievalMode;
  }) =>
    request<ConversationSummary>('/conversations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateConversation: (
    id: string,
    payload: { title?: string; selected_document_ids?: string[]; retrieval_mode?: RetrievalMode },
  ) =>
    request<ConversationSummary>(`/conversations/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteConversation: (id: string) =>
    request<{ conversation_id: string; deleted: boolean }>(
      `/conversations/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),

  ask: (
    conversationId: string,
    payload: {
      query: string;
      selected_document_ids: string[];
      retrieval_mode: RetrievalMode;
      top_k?: number | null;
    },
  ) =>
    request<Message[]>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
