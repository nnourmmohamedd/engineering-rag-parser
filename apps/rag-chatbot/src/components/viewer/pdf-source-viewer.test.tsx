import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Citation } from '@/lib/types';
import { PdfSourceViewer } from './pdf-source-viewer';

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    citation_id: 'S1',
    chunk_id: 'c1',
    document_id: 'doc1',
    source_filename: 'a.pdf',
    page_numbers: [1],
    section_title: 'Intro',
    supporting_quote: 'quote text',
    content_hash: 'h',
    provenance: [],
    bbox_reliable: false,
    source_document_id: 'registry-doc-1',
    source_available: true,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PdfSourceViewer', () => {
  it('shows the honest "source unavailable" state when no registry document is resolved', () => {
    render(
      <PdfSourceViewer
        citations={[citation({ source_document_id: null, source_available: false })]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument();
    // The preserved quote is still shown even when the source itself can't be opened.
    expect(screen.getByText(/quote text/)).toBeInTheDocument();
  });

  it('shows a load error rather than crashing when the PDF fails to load', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error loading PDF')));
    render(
      <PdfSourceViewer
        citations={[citation()]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText(/could not load this source/i)).toBeInTheDocument();
  });

  it('shows citation navigation controls only when there is more than one citation', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    const { rerender } = render(
      <PdfSourceViewer
        citations={[citation()]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByRole('group', { name: /citation navigation/i })).not.toBeInTheDocument();

    rerender(
      <PdfSourceViewer
        citations={[citation({ citation_id: 'S1' }), citation({ citation_id: 'S2' })]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole('group', { name: /citation navigation/i })).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
  });

  it('disables "previous citation" on the first citation and "next" on the last', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    render(
      <PdfSourceViewer
        citations={[citation({ citation_id: 'S1' }), citation({ citation_id: 'S2' })]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /previous citation/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next citation/i })).not.toBeDisabled();
  });

  it('calls onIndexChange when "next citation" is clicked', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    const user = userEvent.setup();
    const onIndexChange = vi.fn();
    render(
      <PdfSourceViewer
        citations={[citation({ citation_id: 'S1' }), citation({ citation_id: 'S2' })]}
        index={0}
        onIndexChange={onIndexChange}
        onClose={() => {}}
      />,
    );
    await user.click(screen.getByRole('button', { name: /next citation/i }));
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  it('ArrowRight/ArrowLeft keys navigate between citations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    const user = userEvent.setup();
    const onIndexChange = vi.fn();
    render(
      <PdfSourceViewer
        citations={[citation({ citation_id: 'S1' }), citation({ citation_id: 'S2' })]}
        index={0}
        onIndexChange={onIndexChange}
        onClose={() => {}}
      />,
    );
    await user.keyboard('{ArrowRight}');
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  it('closing the dialog calls onClose', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <PdfSourceViewer
        citations={[citation()]}
        index={0}
        onIndexChange={() => {}}
        onClose={onClose}
      />,
    );
    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows filename, page and section in the header', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in this test')));
    render(
      <PdfSourceViewer
        citations={[citation({ page_numbers: [5, 6], section_title: 'Valve Sizing' })]}
        index={0}
        onIndexChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.getByText(/p\.5, 6/)).toBeInTheDocument();
    expect(screen.getByText(/Valve Sizing/)).toBeInTheDocument();
  });
});
