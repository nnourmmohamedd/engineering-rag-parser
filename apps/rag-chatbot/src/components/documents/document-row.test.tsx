import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import type { DocumentSummary } from '@/lib/types';
import { renderWithProviders } from '@/test/render';
import { DocumentRow } from './document-row';

function doc(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    document_id: 'd1',
    display_name: 'Instrumentation-and-Control.pdf',
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

function renderRow(document: DocumentSummary) {
  return renderWithProviders(
    <table>
      <tbody>
        <DocumentRow document={document} />
      </tbody>
    </table>,
  );
}

describe('DocumentRow deletion', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('requires explicit confirmation before deleting', async () => {
    const deleteSpy = vi.spyOn(api, 'deleteDocument');
    const user = userEvent.setup();
    renderRow(doc());

    await user.click(screen.getByRole('button', { name: /Actions for/ }));
    await user.click(await screen.findByText('Delete'));

    expect(
      await screen.findByText(/Delete "Instrumentation-and-Control\.pdf"\?/),
    ).toBeInTheDocument();
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it('explains the impact on search and citations in the confirmation', async () => {
    const user = userEvent.setup();
    renderRow(doc());

    await user.click(screen.getByRole('button', { name: /Actions for/ }));
    await user.click(await screen.findByText('Delete'));

    expect(screen.getByText(/can no longer be searched/)).toBeInTheDocument();
    expect(screen.getByText(/citations will be marked as unavailable/)).toBeInTheDocument();
  });

  it('only calls the delete API after the confirm button is clicked', async () => {
    const deleteSpy = vi.spyOn(api, 'deleteDocument').mockResolvedValue({
      document_id: 'd1',
      deleted: true,
      chunks_removed: 5,
      display_name: 'x',
    });
    const user = userEvent.setup();
    renderRow(doc());

    await user.click(screen.getByRole('button', { name: /Actions for/ }));
    await user.click(await screen.findByText('Delete'));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Delete document' }));

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith('d1'));
  });

  it('cancelling leaves the document untouched', async () => {
    const deleteSpy = vi.spyOn(api, 'deleteDocument');
    const user = userEvent.setup();
    renderRow(doc());

    await user.click(screen.getByRole('button', { name: /Actions for/ }));
    await user.click(await screen.findByText('Delete'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(deleteSpy).not.toHaveBeenCalled();
  });
});
