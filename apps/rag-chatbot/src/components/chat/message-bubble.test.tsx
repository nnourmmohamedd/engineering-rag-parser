import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CitationViewerProvider } from '@/hooks/use-citation-viewer';
import type { Citation, Message } from '@/lib/types';
import { MessageBubble } from './message-bubble';

function baseMessage(overrides: Partial<Message> = {}): Message {
  return {
    message_id: 'm1',
    conversation_id: 'c1',
    role: 'assistant',
    content: 'Control valves regulate flow [S1].',
    created_at: new Date().toISOString(),
    status: 'answered',
    retrieval_mode: 'vector',
    selected_document_ids: ['doc1'],
    citations: [],
    stage_timings: {},
    grounding: { status: 'PASS' },
    model_tag: 'qwen3:4b',
    model_digest: 'abc123',
    provider: 'ollama',
    error_code: null,
    ...overrides,
  };
}

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    citation_id: 'S1',
    chunk_id: 'c1',
    document_id: 'doc1',
    source_filename: 'a.pdf',
    page_numbers: [1],
    section_title: null,
    supporting_quote: 'quote',
    content_hash: 'h',
    provenance: [],
    bbox_reliable: false,
    source_document_id: 'registry-doc-1',
    source_available: true,
    ...overrides,
  };
}

function renderMessage(message: Message) {
  return render(
    <CitationViewerProvider>
      <MessageBubble message={message} />
    </CitationViewerProvider>,
  );
}

describe('MessageBubble', () => {
  it('renders a user message right-aligned without a status badge', () => {
    renderMessage(baseMessage({ role: 'user', content: 'What is a valve?' }));
    expect(screen.getByText('What is a valve?')).toBeInTheDocument();
    expect(screen.queryByText('Grounded answer')).not.toBeInTheDocument();
  });

  it('renders an answered assistant message with its status badge', () => {
    renderMessage(baseMessage());
    expect(screen.getByText('Grounded answer')).toBeInTheDocument();
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('renders a refusal distinctly from a real answer', () => {
    renderMessage(
      baseMessage({
        status: 'insufficient_evidence',
        content: 'I could not find enough evidence to answer this question reliably.',
      }),
    );
    expect(screen.getByText(/Insufficient evidence/)).toBeInTheDocument();
  });

  it('renders a generation failure without presenting unvalidated text as an answer', () => {
    renderMessage(baseMessage({ status: 'failed', content: '', error_code: 'LLM_UNAVAILABLE' }));
    expect(screen.getByText(/Could not answer/)).toBeInTheDocument();
    expect(screen.getByText(/No answer text was produced/)).toBeInTheDocument();
  });

  it('shows each citation as a distinct source card', () => {
    renderMessage(baseMessage({ citations: [citation()] }));
    expect(screen.getByText('Sources (1)')).toBeInTheDocument();
    // The answer text also contains an inline [S1] marker (now its own clickable element),
    // so the source-card badge is disambiguated by count rather than a single getByText.
    expect(screen.getAllByText('[S1]')).toHaveLength(2);
  });

  it('sanitises raw HTML embedded in the answer text (XSS defence)', () => {
    renderMessage(baseMessage({ content: '<img src=x onerror="window.__pwned=true">Safe text' }));
    expect(screen.getByText(/Safe text/)).toBeInTheDocument();
    expect(document.querySelector('img[onerror]')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
  });

  it('sanitises a script tag embedded in the answer text', () => {
    renderMessage(baseMessage({ content: 'Also safe<script>window.__pwned2=true</script>' }));
    expect(screen.getByText(/Also safe/)).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned2).toBeUndefined();
  });

  it('sanitises a javascript: URL embedded as a markdown link', () => {
    renderMessage(baseMessage({ content: '[click me](javascript:window.__pwned3=true)' }));
    const link = screen.queryByRole('link', { name: 'click me' });
    if (link) {
      expect(link.getAttribute('href')).not.toMatch(/^javascript:/i);
    }
    expect((window as unknown as Record<string, unknown>).__pwned3).toBeUndefined();
  });

  describe('inline [S<n>] citation markers', () => {
    it('renders an inline citation marker as a clickable element, not literal text', () => {
      renderMessage(
        baseMessage({ content: 'Valves regulate flow [S1].', citations: [citation()] }),
      );
      // The literal bracket text is now inside a button, not a plain text node.
      expect(screen.getByRole('button', { name: /open citation s1 source/i })).toBeInTheDocument();
    });

    it('clicking an inline marker opens the PDF viewer for that citation', async () => {
      const user = userEvent.setup();
      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockRejectedValue(new Error('not available in jsdom'));
      try {
        renderMessage(
          baseMessage({ content: 'Valves regulate flow [S1].', citations: [citation()] }),
        );
        await user.click(screen.getByRole('button', { name: /open citation s1 source/i }));
        expect(await screen.findByRole('dialog')).toBeInTheDocument();
      } finally {
        global.fetch = originalFetch;
      }
    });

    it('a marker with no matching citation_id (e.g. stripped/unknown) is left as plain text', () => {
      renderMessage(baseMessage({ content: 'Unrelated [S9] marker.', citations: [citation()] }));
      // [S9] has no corresponding citation in this message -> rendered as an inert link,
      // not a button claiming to open something that doesn't exist.
      expect(screen.queryByRole('button', { name: /open citation s9/i })).not.toBeInTheDocument();
    });
  });
});
