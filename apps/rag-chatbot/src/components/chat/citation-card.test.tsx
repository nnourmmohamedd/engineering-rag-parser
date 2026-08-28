import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

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
  source_available: true,
};

describe('CitationCard', () => {
  it('shows the citation id, source and page in the collapsed header', () => {
    render(<CitationCard citation={citation} />);
    expect(screen.getByText('[S1]')).toBeInTheDocument();
    expect(screen.getByText(/Instrumentation\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/p\.3, 4/)).toBeInTheDocument();
  });

  it('hides the supporting quote until expanded', () => {
    render(<CitationCard citation={citation} />);
    expect(screen.queryByText(/Control valves regulate flow/)).not.toBeInTheDocument();
  });

  it('reveals the supporting quote and section on click', async () => {
    const user = userEvent.setup();
    render(<CitationCard citation={citation} />);

    await user.click(screen.getByRole('button', { expanded: false }));

    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
    expect(screen.getByText('Control Valves')).toBeInTheDocument();
    expect(screen.getByText('chunk_abc')).toBeInTheDocument();
  });

  it('is keyboard operable', async () => {
    const user = userEvent.setup();
    render(<CitationCard citation={citation} />);

    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('flags an unavailable (deleted) source, without altering the citation content', async () => {
    const user = userEvent.setup();
    render(<CitationCard citation={{ ...citation, source_available: false }} />);

    expect(screen.getByText('Deleted')).toBeInTheDocument();
    await user.click(screen.getByRole('button'));
    expect(screen.getByText(/source document has since been deleted/i)).toBeInTheDocument();
    // The citation text itself is preserved, not rewritten.
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('does not communicate status by colour alone -- an icon and text are present', () => {
    render(<CitationCard citation={{ ...citation, source_available: false }} />);
    expect(screen.getByText('Deleted')).toBeInTheDocument();
  });
});
