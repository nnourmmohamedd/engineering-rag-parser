import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import type { DocumentSummary } from '@/lib/types';
import { renderWithProviders } from '@/test/render';
import { DocumentSelector } from './document-selector';

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

describe('DocumentSelector', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('only lists READY documents as selectable', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([
      doc({ document_id: 'ready1', display_name: 'Ready One.pdf', status: 'READY' }),
      doc({ document_id: 'processing1', display_name: 'Processing One.pdf', status: 'PROCESSING' }),
    ]);

    renderWithProviders(<DocumentSelector selected={[]} onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Ready One.pdf')).toBeInTheDocument());
    expect(screen.queryByText('Processing One.pdf')).not.toBeInTheDocument();
    expect(screen.getByText(/1 document.*not yet ready/)).toBeInTheDocument();
  });

  it('shows an explicit empty state when nothing is ready', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({ status: 'PROCESSING' })]);
    renderWithProviders(<DocumentSelector selected={[]} onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/No documents are ready yet/)).toBeInTheDocument());
  });

  it('calls onChange with the added id when a checkbox is checked', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({ document_id: 'd1' })]);
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<DocumentSelector selected={[]} onChange={onChange} />);

    await waitFor(() => screen.getByRole('checkbox'));
    await user.click(screen.getByRole('checkbox'));

    expect(onChange).toHaveBeenCalledWith(['d1']);
  });

  it('calls onChange with the id removed when an already-selected checkbox is unchecked', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({ document_id: 'd1' })]);
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<DocumentSelector selected={['d1']} onChange={onChange} />);

    await waitFor(() => screen.getByRole('checkbox'));
    await user.click(screen.getByRole('checkbox'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('shows the current selection count', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([
      doc({ document_id: 'd1' }),
      doc({ document_id: 'd2', display_name: 'Second.pdf', sha256: 'b'.repeat(64) }),
    ]);
    renderWithProviders(<DocumentSelector selected={['d1', 'd2']} onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/2 selected/)).toBeInTheDocument());
  });

  it('the clear button empties the selection', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue([doc({ document_id: 'd1' })]);
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<DocumentSelector selected={['d1']} onChange={onChange} />);

    await waitFor(() => screen.getByText('Clear'));
    await user.click(screen.getByText('Clear'));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});
