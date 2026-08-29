import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CitationViewerProvider } from '@/hooks/use-citation-viewer';
import type { Citation } from '@/lib/types';
import { CitationCard } from './citation-card';

const citation: Citation = {
  citation_id: 'S1',
  chunk_id: 'chunk_abc',
  document_id: 'doc1',
  source_filename: 'Instrumentation.pdf',
  page_numbers: [3, 4],
  section_title: 'Control Valves',
  supporting_quote: 'Control valves regulate flow.',
  content_hash: 'h1',
  provenance: [],
  bbox_reliable: false,
  source_document_id: 'registry-doc-1',
  source_available: true,
};

function renderCard(props: Partial<Parameters<typeof CitationCard>[0]> = {}) {
  return render(
    <CitationViewerProvider>
      <CitationCard citation={citation} {...props} />
    </CitationViewerProvider>,
  );
}

describe('CitationCard', () => {
  it('shows the citation id, source and page in the collapsed header', () => {
    renderCard();
    expect(screen.getByText('[S1]')).toBeInTheDocument();
    expect(screen.getByText(/Instrumentation\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/p\.3, 4/)).toBeInTheDocument();
  });

  it('hides the supporting quote until expanded', () => {
    renderCard();
    expect(screen.queryByText(/Control valves regulate flow/)).not.toBeInTheDocument();
  });

  it('reveals the supporting quote and section on click', async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole('button', { expanded: false }));

    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
    expect(screen.getByText('Control Valves')).toBeInTheDocument();
    expect(screen.getByText('chunk_abc')).toBeInTheDocument();
  });

  it('is keyboard operable', async () => {
    const user = userEvent.setup();
    renderCard();

    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('flags an unavailable (deleted) source, without altering the citation content', async () => {
    const user = userEvent.setup();
    renderCard({ citation: { ...citation, source_available: false } });

    expect(screen.getByText('Deleted')).toBeInTheDocument();
    await user.click(screen.getByRole('button'));
    expect(screen.getByText(/source document has since been deleted/i)).toBeInTheDocument();
    // The citation text itself is preserved, not rewritten.
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('does not communicate status by colour alone -- an icon and text are present', () => {
    renderCard({ citation: { ...citation, source_available: false } });
    expect(screen.getByText('Deleted')).toBeInTheDocument();
  });

  it('offers "Open source" once expanded, when the source is available', async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole('button', { expanded: false }));
    expect(screen.getByRole('button', { name: /open source/i })).toBeInTheDocument();
  });

  it('does not offer "Open source" for an unavailable (deleted) source', async () => {
    const user = userEvent.setup();
    renderCard({ citation: { ...citation, source_available: false } });
    await user.click(screen.getByRole('button', { name: /S1/ }));
    expect(screen.queryByRole('button', { name: /open source/i })).not.toBeInTheDocument();
  });

  it('does not offer "Open source" when no registry document could be resolved', async () => {
    const user = userEvent.setup();
    renderCard({ citation: { ...citation, source_document_id: null } });
    await user.click(screen.getByRole('button', { name: /S1/ }));
    expect(screen.queryByRole('button', { name: /open source/i })).not.toBeInTheDocument();
  });

  it('clicking "Open source" opens the PDF viewer dialog', async () => {
    const user = userEvent.setup();
    // jsdom has no real PDF.js/canvas backend; the loader is expected to reject, which the
    // viewer surfaces as its own error state -- this test only asserts the dialog opened.
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockRejectedValue(new Error('not available in jsdom'));
    try {
      renderCard();
      await user.click(screen.getByRole('button', { expanded: false }));
      await user.click(screen.getByRole('button', { name: /open source/i }));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
    } finally {
      global.fetch = originalFetch;
    }
  });
});
