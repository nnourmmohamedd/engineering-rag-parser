/**
 * Types mirroring the backend's `/api/v1` schemas (src/engineering_rag/chatbot/schemas.py).
 *
 * Kept hand-written rather than generated so the compiler flags a drift the
 * moment a response shape changes, instead of a runtime `undefined` surfacing
 * three components deep.
 */

export type DocumentStatus =
  | 'UPLOADED'
  | 'PROCESSING'
  | 'READY'
  | 'FAILED'
  | 'INTERRUPTED'
  | 'DELETING'
  | 'DELETED';

export type JobState = 'QUEUED' | 'RUNNING' | 'READY' | 'FAILED' | 'CANCELLED' | 'INTERRUPTED';

export type JobStage =
  | 'QUEUED'
  | 'VALIDATING'
  | 'PARSING'
  | 'PARSER_VALIDATION'
  | 'CHUNKING'
  | 'CHUNK_VALIDATION'
  | 'EMBEDDING'
  | 'VECTOR_INDEXING'
  | 'BM25_INDEXING'
  | 'INDEX_VALIDATION'
  | 'ACTIVATION'
  | 'CLEANUP';

export type RetrievalMode = 'vector' | 'hybrid' | 'vector-rerank' | 'hybrid-rerank';

/** The backend's typed error envelope. The UI branches on `code`, never on text. */
export interface ApiErrorPayload {
  code: string;
  message: string;
  retryable: boolean;
  correlation_id: string | null;
}

export interface DocumentSummary {
  document_id: string;
  display_name: string;
  status: DocumentStatus;
  parser_profile: string;
  byte_size: number;
  page_count: number | null;
  total_chunks: number | null;
  warning_count: number;
  created_at: string;
  updated_at: string;
  sha256: string;
}

export interface StageTiming {
  stage: JobStage;
  duration_s: number;
}

export interface JobSummary {
  job_id: string;
  document_id: string;
  job_type: string;
  state: JobState;
  stage: JobStage;
  progress: number;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  stage_timings: StageTiming[];
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  cancel_requested: boolean;
}

export interface DocumentDetail {
  document: DocumentSummary;
  warnings: string[];
  validation_summary: Record<string, unknown>;
  parser_run_id: string | null;
  chunk_run_id: string | null;
  index_version: string | null;
  jobs: JobSummary[];
}

export interface DocumentPreview {
  document_id: string;
  display_name: string;
  markdown: string;
  truncated: boolean;
  total_characters: number;
}

export interface UploadResponse {
  document: DocumentSummary;
  job: JobSummary | null;
  duplicate_of: string | null;
}

export interface ParserProfileInfo {
  id: string;
  label: string;
  description: string;
}

export interface Capabilities {
  version: string;
  parser_profiles: ParserProfileInfo[];
  retrieval_modes: RetrievalMode[];
  default_retrieval_mode: RetrievalMode;
  accepted_extensions: string[];
  accepted_media_types: string[];
  max_upload_bytes: number;
  max_pages: number;
  provider: string;
  model_tag: string | null;
  model_digest: string | null;
  generation_is_cpu_bound: boolean;
}

export interface DependencyStatus {
  name: string;
  available: boolean;
  detail: string;
}

export interface SystemStatus {
  version: string;
  dependencies: DependencyStatus[];
  documents_total: number;
  documents_ready: number;
  jobs_active: number;
  worker_running: boolean;
  data_root_label: string;
}

export interface Citation {
  citation_id: string;
  chunk_id: string | null;
  document_id: string | null;
  source_filename: string | null;
  page_numbers: number[];
  section_title: string | null;
  supporting_quote: string | null;
  content_hash: string | null;
  /** False once the cited document has been deleted; the citation itself is never rewritten. */
  source_available: boolean;
}

export interface Message {
  message_id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  status: string | null;
  retrieval_mode: string | null;
  selected_document_ids: string[];
  citations: Citation[];
  stage_timings: Record<string, number>;
  grounding: {
    status?: string;
    checks_passed?: string[];
    checks_failed?: string[];
    warnings?: string[];
    citation_coverage_ratio?: number | null;
    repair_attempted?: boolean | null;
  };
  model_tag: string | null;
  model_digest: string | null;
  provider: string | null;
  error_code: string | null;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  selected_document_ids: string[];
  retrieval_mode: RetrievalMode;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  conversation: ConversationSummary;
  messages: Message[];
}

/** One live ingestion progress event, delivered over SSE. */
export interface JobEvent {
  type: 'snapshot' | 'stage' | 'terminal';
  job_id: string;
  document_id: string;
  state?: JobState;
  stage?: JobStage;
  progress?: number;
  error_code?: string | null;
}
