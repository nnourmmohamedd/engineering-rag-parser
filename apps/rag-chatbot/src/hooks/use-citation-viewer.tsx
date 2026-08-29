import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import type { Citation } from '@/lib/types';
import { PdfSourceViewer } from '@/components/viewer/pdf-source-viewer';

interface ViewerState {
  citations: Citation[];
  index: number;
}

interface CitationViewerContextValue {
  /** Open the viewer on `citations[index]`, with prev/next cycling through the rest of `citations`. */
  openCitation: (citations: Citation[], index: number) => void;
  close: () => void;
}

const CitationViewerContext = createContext<CitationViewerContextValue | null>(null);

/** Mounted once near the app root so any citation card or inline `[S<n>]` marker, anywhere
 * in the tree, can open the same viewer without prop-drilling -- and the underlying chat
 * page/conversation never unmounts or loses scroll position while it's open. */
export function CitationViewerProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ViewerState | null>(null);

  const openCitation = useCallback((citations: Citation[], index: number) => {
    setState({ citations, index });
  }, []);
  const close = useCallback(() => setState(null), []);
  const setIndex = useCallback((index: number) => {
    setState((prev) => (prev ? { ...prev, index } : prev));
  }, []);

  const value = useMemo(() => ({ openCitation, close }), [openCitation, close]);

  return (
    <CitationViewerContext.Provider value={value}>
      {children}
      {state && (
        <PdfSourceViewer
          citations={state.citations}
          index={state.index}
          onIndexChange={setIndex}
          onClose={close}
        />
      )}
    </CitationViewerContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCitationViewer(): CitationViewerContextValue {
  const ctx = useContext(CitationViewerContext);
  if (!ctx) {
    throw new Error('useCitationViewer must be used within a CitationViewerProvider');
  }
  return ctx;
}
