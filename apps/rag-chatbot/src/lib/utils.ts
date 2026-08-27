import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Human-readable byte size. Uses binary units, which is what a file manager shows. */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  const rounded =
    value >= 10 || exponent === 0
      ? String(Math.round(value))
      : value.toFixed(1).replace(/\.0$/, '');
  return `${rounded} ${units[exponent]}`;
}

/** Duration for humans: seconds under a minute, then m/s, then h/m. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Shorten a long filename while keeping its extension visible, so a user can
 * still tell `spec-rev-A.pdf` from `spec-rev-B.pdf` in a narrow column.
 */
export function truncateMiddle(text: string, max = 40): string {
  if (text.length <= max) return text;
  const keep = Math.floor((max - 1) / 2);
  return `${text.slice(0, keep)}…${text.slice(-keep)}`;
}

/** Turn a stage id into a short human label for progress display. */
export function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    QUEUED: 'Queued',
    VALIDATING: 'Validating file',
    PARSING: 'Parsing document',
    PARSER_VALIDATION: 'Checking parse quality',
    CHUNKING: 'Splitting into chunks',
    CHUNK_VALIDATION: 'Checking chunks',
    EMBEDDING: 'Generating embeddings',
    VECTOR_INDEXING: 'Indexing (vector)',
    BM25_INDEXING: 'Indexing (keyword)',
    INDEX_VALIDATION: 'Verifying indexes',
    ACTIVATION: 'Activating',
    CLEANUP: 'Cleaning up',
  };
  return labels[stage] ?? stage;
}
