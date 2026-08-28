import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useJobEvents } from './use-job-events';

interface MockEventSourceInstance {
  url: string;
  emit: (data: unknown) => void;
  close: () => void;
  onmessage: ((event: MessageEvent) => void) | null;
}

interface MockEventSourceCtor {
  instances: MockEventSourceInstance[];
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useJobEvents', () => {
  it('does nothing when jobId is null', () => {
    const { result } = renderHook(() => useJobEvents(null), { wrapper });
    expect(result.current.latest).toBeNull();
  });

  it('surfaces each event as it arrives', async () => {
    const { result } = renderHook(() => useJobEvents('job-1'), { wrapper });
    const MockSource = (window as unknown as { __MockEventSource: MockEventSourceCtor })
      .__MockEventSource;
    const instance = MockSource.instances.at(-1)!;

    act(() =>
      instance.emit({
        type: 'stage',
        job_id: 'job-1',
        document_id: 'd1',
        stage: 'PARSING',
        progress: 0.2,
      }),
    );

    await waitFor(() => expect(result.current.latest?.stage).toBe('PARSING'));
  });

  it('closes the connection after a terminal event', async () => {
    const { result } = renderHook(() => useJobEvents('job-2'), { wrapper });
    const MockSource = (window as unknown as { __MockEventSource: MockEventSourceCtor })
      .__MockEventSource;
    const instance = MockSource.instances.at(-1)!;
    const closeSpy = vi.spyOn(instance, 'close');

    act(() =>
      instance.emit({ type: 'terminal', job_id: 'job-2', document_id: 'd1', state: 'READY' }),
    );

    await waitFor(() => expect(result.current.latest?.type).toBe('terminal'));
    expect(closeSpy).toHaveBeenCalled();
  });

  it('malformed event data is dropped rather than crashing', async () => {
    const { result } = renderHook(() => useJobEvents('job-3'), { wrapper });
    const MockSource = (window as unknown as { __MockEventSource: MockEventSourceCtor })
      .__MockEventSource;
    const instance = MockSource.instances.at(-1)!;

    act(() => instance.onmessage?.({ data: 'not json' } as MessageEvent));

    // No crash, and no event was recorded.
    expect(result.current.latest).toBeNull();
  });
});
