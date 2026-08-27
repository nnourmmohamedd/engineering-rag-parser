import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Message } from '@/lib/types';
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

describe('MessageBubble', () => {
  it('renders a user message right-aligned without a status badge', () => {
    render(<MessageBubble message={baseMessage({ role: 'user', content: 'What is a valve?' })} />);
    expect(screen.getByText('What is a valve?')).toBeInTheDocument();
    expect(screen.queryByText('Grounded answer')).not.toBeInTheDocument();
  });

  it('renders an answered assistant message with its status badge', () => {
    render(<MessageBubble message={baseMessage()} />);
    expect(screen.getByText('Grounded answer')).toBeInTheDocument();
    expect(screen.getByText(/Control valves regulate flow/)).toBeInTheDocument();
  });

  it('renders a refusal distinctly from a real answer', () => {
    render(
      <MessageBubble
        message={baseMessage({
          status: 'insufficient_evidence',
          content: 'I could not find enough evidence to answer this question reliably.',
        })}
      />,
    );
    expect(screen.getByText(/Insufficient evidence/)).toBeInTheDocument();
  });

  it('renders a generation failure without presenting unvalidated text as an answer', () => {
    render(
      <MessageBubble
        message={baseMessage({ status: 'failed', content: '', error_code: 'LLM_UNAVAILABLE' })}
      />,
    );
    expect(screen.getByText(/Could not answer/)).toBeInTheDocument();
    expect(screen.getByText(/No answer text was produced/)).toBeInTheDocument();
  });

  it('shows each citation as a distinct source card', () => {
    render(
      <MessageBubble
        message={baseMessage({
          citations: [
            {
              citation_id: 'S1',
              chunk_id: 'c1',
              document_id: 'doc1',
              source_filename: 'a.pdf',
              page_numbers: [1],
              section_title: null,
              supporting_quote: 'quote',
              content_hash: 'h',
              source_available: true,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText('Sources (1)')).toBeInTheDocument();
    expect(screen.getByText('[S1]')).toBeInTheDocument();
  });

  it('sanitises raw HTML embedded in the answer text (XSS defence)', () => {
    render(
      <MessageBubble
        message={baseMessage({ content: '<img src=x onerror="window.__pwned=true">Safe text' })}
      />,
    );
    expect(screen.getByText(/Safe text/)).toBeInTheDocument();
    expect(document.querySelector('img[onerror]')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
  });

  it('sanitises a script tag embedded in the answer text', () => {
    render(
      <MessageBubble
        message={baseMessage({ content: 'Also safe<script>window.__pwned2=true</script>' })}
      />,
    );
    expect(screen.getByText(/Also safe/)).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned2).toBeUndefined();
  });
});
