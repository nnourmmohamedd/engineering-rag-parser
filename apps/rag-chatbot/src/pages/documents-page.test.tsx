import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from '@/lib/api';
import type { Capabilities, DocumentSummary } from '@/lib/types';
import { renderWithProviders } from '@/test/render';
import { DocumentsPage } from './documents-page';

const capabilities: Capabilities = {
  version: '1.0.0',
  parser_profiles: [{ id: 'default', label: 'Default', description: '' }],
  retrieval_modes: ['vector'],
  default_retrieval_mode: 'vector',
  accepted_extensions: ['.pdf'],
  accepted_media_types: ['application/pdf'],
  max_upload_bytes: 10_000_000,
  max_pages: 2000,
  provider: 'ollama',
  model_tag: 'qwen3:4b',
  model_digest: 'abc',
  generation_is_cpu_bound: true,
};

function doc(overrides: Partial<DocumentSummary>): DocumentSummary {
  return {
    document_id: 'd1',
    display_name: 'Report.pdf',
    status: 'READY',
    parser_profile: 'default',
    byte_size: 1000,
    page_count: 10,
    total_chunks: 5,
    warning_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    sha256: 'a'.repeat(64),
    ...overrides,
  };
}

describe('DocumentsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
  });

  it('shows an empty state with no documents', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([]);
    renderWithProviders(<DocumentsPage />);
    await waitFor(() => expect(screen.getByText('No documents yet')).toBeInTheDocument());
  });

  it('shows a typed error state when listing fails', async () => {
    vi.spyOn(api, 'listDocuments').mockRejectedValue(
      new ApiError('INTERNAL_ERROR', 'The backend could not list documents.'),
    );
    renderWithProviders(<DocumentsPage />);
    await waitFor(() =>
      expect(screen.getByText('The backend could not list documents.')).toBeInTheDocument(),
    );
  });

  it('renders the document table once documents load', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({})]);
    renderWithProviders(<DocumentsPage />);
    await waitFor(() => expect(screen.getByText('Report.pdf')).toBeInTheDocument());
    // "Ready" also appears as a status-filter option, so scope to the table row.
    expect(within(screen.getByRole('table')).getByText('Ready')).toBeInTheDocument();
  });

  it('filters the empty-vs-no-match message once a search excludes everything', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({})]);
    const user = userEvent.setup();
    renderWithProviders(<DocumentsPage />);
    await waitFor(() => screen.getByText('Report.pdf'));

    await user.type(screen.getByLabelText('Search documents by name'), 'no-such-file');

    await waitFor(() =>
      expect(screen.getByText('No documents match your filters')).toBeInTheDocument(),
    );
  });
});
