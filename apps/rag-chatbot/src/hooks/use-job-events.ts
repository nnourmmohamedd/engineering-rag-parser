import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api } from '@/lib/api';
import type { JobEvent } from '@/lib/types';
import { documentKeys } from './use-documents';

/**
 * Live progress for one ingestion job via SSE.
 *
 * Every event the backend sends is real, already-reached pipeline state --
 * this hook never interpolates or animates a value the server hasn't
 * reported. When a `terminal` event (or a `snapshot` of an already-finished
 * job) arrives, the connection closes and the document list is invalidated
 * so the rest of the UI picks up the final state.
 */
export function useJobEvents(jobId: string | null) {
  const queryClient = useQueryClient();
  const [latest, setLatest] = useState<JobEvent | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setLatest(null);
    setConnectionError(false);
    if (!jobId) return;

    const source = api.jobEvents(jobId);
    sourceRef.current = source;

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as JobEvent;
        setLatest(event);
        if (
          event.type === 'terminal' ||
          (event.type === 'snapshot' && isTerminalState(event.state))
        ) {
          queryClient.invalidateQueries({ queryKey: documentKeys.all });
          if (event.document_id) {
            queryClient.invalidateQueries({ queryKey: documentKeys.detail(event.document_id) });
          }
          source.close();
        }
      } catch {
        // A malformed event is dropped rather than crashing the stream.
      }
    };

    source.onerror = () => {
      setConnectionError(true);
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [jobId, queryClient]);

  return { latest, connectionError };
}

function isTerminalState(state: JobEvent['state']): boolean {
  return (
    state === 'READY' || state === 'FAILED' || state === 'CANCELLED' || state === 'INTERRUPTED'
  );
}
