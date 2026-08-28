import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api } from './api';

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it('parses a successful JSON response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([{ document_id: 'd1' }]));
    const result = await api.listDocuments();
    expect(result).toEqual([{ document_id: 'd1' }]);
  });

  it('sends the request to the /api/v1 prefix', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: 'ok', version: '1.0.0' }));
    await api.health();
    expect(fetch).toHaveBeenCalledWith('/api/v1/health', expect.anything());
  });

  it('throws a typed ApiError with the backend error code on failure', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        { error: { code: 'DOCUMENT_NOT_FOUND', message: 'Document not found.', retryable: false } },
        {
          status: 404,
          headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'corr-1' },
        },
      ),
    );

    await expect(api.getDocument('missing')).rejects.toMatchObject({
      code: 'DOCUMENT_NOT_FOUND',
      message: 'Document not found.',
      retryable: false,
      status: 404,
      correlationId: 'corr-1',
    });
  });

  it('produces a retryable NETWORK_UNREACHABLE error when fetch itself throws', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'));

    let caught: unknown;
    try {
      await api.health();
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe('NETWORK_UNREACHABLE');
    expect((caught as ApiError).retryable).toBe(true);
  });

  it('falls back to a generic error when the failure body is not JSON', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('Internal Server Error', { status: 500 }));
    await expect(api.health()).rejects.toMatchObject({ code: 'HTTP_500', retryable: true });
  });

  it('never sets Content-Type for a FormData upload body', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ document: {}, job: null, duplicate_of: null }),
    );
    const file = new File([new Uint8Array([1, 2, 3])], 'a.pdf', { type: 'application/pdf' });
    await api.uploadDocument(file, 'default');

    const [, init] = vi.mocked(fetch).mock.calls[0]!;
    const headers = init?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBeUndefined();
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it('marks the selected document ids on ask()', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));
    await api.ask('c1', {
      query: 'q',
      selected_document_ids: ['d1', 'd2'],
      retrieval_mode: 'vector',
    });

    const [, init] = vi.mocked(fetch).mock.calls[0]!;
    const body = JSON.parse(init?.body as string);
    expect(body.selected_document_ids).toEqual(['d1', 'd2']);
  });
});
