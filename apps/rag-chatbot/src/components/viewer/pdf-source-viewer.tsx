import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileWarning,
  Loader2,
  Quote,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { api } from '@/lib/api';
import {
  bboxToViewportRect,
  quoteToViewportRects,
  type ViewportRect,
} from '@/lib/citation-highlight';
import { loadPdfDocument, type PDFDocumentProxy } from '@/lib/pdf';
import type { Citation } from '@/lib/types';
import { cn } from '@/lib/utils';

const MIN_SCALE = 0.6;
const MAX_SCALE = 3.0;
const SCALE_STEP = 0.2;

interface PdfSourceViewerProps {
  citations: Citation[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}

/** Modal PDF.js viewer: jumps to the cited page and highlights the exact supporting
 * passage whenever trustworthy coordinates or a verified text-layer match are available
 * (see `src/lib/citation-highlight.ts`) -- never fabricated. Mounted by
 * `CitationViewerProvider` so opening it never navigates away from or unmounts the
 * conversation underneath it. */
export function PdfSourceViewer({
  citations,
  index,
  onIndexChange,
  onClose,
}: PdfSourceViewerProps) {
  const citation = citations[index];
  const canGoPrev = index > 0;
  const canGoNext = index < citations.length - 1;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'ArrowLeft' && canGoPrev) onIndexChange(index - 1);
      if (event.key === 'ArrowRight' && canGoNext) onIndexChange(index + 1);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [index, canGoPrev, canGoNext, onIndexChange]);

  if (!citation) return null;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="grid h-[90vh] w-[95vw] max-w-6xl grid-rows-[auto_1fr] gap-0 overflow-hidden p-0 sm:rounded-lg"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogTitle className="sr-only">
          Source: {citation.source_filename ?? 'document'}, citation {citation.citation_id}
        </DialogTitle>
        <DialogDescription className="sr-only">
          PDF source viewer showing the passage cited by {citation.citation_id}
          {citation.page_numbers.length > 0 && `, page ${citation.page_numbers.join(', ')}`}.
        </DialogDescription>
        <ViewerHeader
          citation={citation}
          citationCount={citations.length}
          index={index}
          canGoPrev={canGoPrev}
          canGoNext={canGoNext}
          onPrev={() => onIndexChange(index - 1)}
          onNext={() => onIndexChange(index + 1)}
        />
        {/* Remounts the loader/canvas cleanly on every citation switch -- no stale
            PDF.js document or in-flight render task to reconcile across citations. */}
        <PdfViewerBody key={citation.citation_id} citation={citation} />
      </DialogContent>
    </Dialog>
  );
}

function ViewerHeader({
  citation,
  citationCount,
  index,
  canGoPrev,
  canGoNext,
  onPrev,
  onNext,
}: {
  citation: Citation;
  citationCount: number;
  index: number;
  canGoPrev: boolean;
  canGoNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    // pr-12 keeps the citation-nav controls clear of DialogContent's own fixed
    // top-right close button, which would otherwise intercept clicks on "Next citation".
    <div className="flex flex-wrap items-center gap-2 border-b bg-card px-4 py-2.5 pr-12">
      <Badge variant="outline" className="shrink-0">
        [{citation.citation_id}]
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {citation.source_filename ?? 'Unknown source'}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {citation.page_numbers.length > 0 && `p.${citation.page_numbers.join(', ')}`}
          {citation.section_title && ` · ${citation.section_title}`}
          {citation.chunk_id && ` · `}
          {citation.chunk_id && <span className="font-mono">{citation.chunk_id}</span>}
        </p>
      </div>
      {citationCount > 1 && (
        <div
          className="flex shrink-0 items-center gap-1"
          role="group"
          aria-label="Citation navigation"
        >
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onPrev}
            disabled={!canGoPrev}
            aria-label="Previous citation"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Button>
          <span className="text-xs text-muted-foreground">
            {index + 1} / {citationCount}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onNext}
            disabled={!canGoNext}
            aria-label="Next citation"
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      )}
    </div>
  );
}

type LoadState =
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'error'; message: string }
  | { status: 'ready'; doc: PDFDocumentProxy; pageCount: number };

function PdfViewerBody({ citation }: { citation: Citation }) {
  const [load, setLoad] = useState<LoadState>({ status: 'loading' });
  const [pageNumber, setPageNumber] = useState(citation.page_numbers[0] ?? 1);
  const [scale, setScale] = useState(1.2);

  useEffect(() => {
    if (!citation.source_document_id) {
      setLoad({ status: 'unavailable' });
      return;
    }
    let cancelled = false;
    setLoad({ status: 'loading' });
    loadPdfDocument(api.documentSourceUrl(citation.source_document_id))
      .then((doc) => {
        if (cancelled) return;
        setLoad({ status: 'ready', doc, pageCount: doc.numPages });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoad({
          status: 'error',
          message: error instanceof Error ? error.message : 'Could not load the PDF.',
        });
      });
    return () => {
      cancelled = true;
    };
  }, [citation.source_document_id]);

  if (load.status === 'unavailable') {
    return <SourceUnavailable citation={citation} />;
  }
  if (load.status === 'error') {
    return <ViewerError message={load.message} />;
  }
  if (load.status === 'loading') {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
        <span className="sr-only">Loading PDF…</span>
      </div>
    );
  }

  return (
    <div className="grid min-h-0 grid-rows-[1fr_auto]">
      <PdfPageCanvas doc={load.doc} pageNumber={pageNumber} scale={scale} citation={citation} />
      <ViewerFooter
        citation={citation}
        pageNumber={pageNumber}
        pageCount={load.pageCount}
        scale={scale}
        onPageChange={setPageNumber}
        onScaleChange={setScale}
      />
    </div>
  );
}

function SourceUnavailable({ citation }: { citation: Citation }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <FileWarning className="h-8 w-8 text-warning" aria-hidden="true" />
      <p className="max-w-sm text-sm text-muted-foreground">
        This source document is no longer available (it may have been deleted). The citation is
        preserved exactly as it was when the answer was generated.
      </p>
      {citation.supporting_quote && <QuotationPanel citation={citation} />}
    </div>
  );
}

function ViewerError({ message }: { message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
      <p className="max-w-sm text-sm text-muted-foreground">
        Could not load this source: {message}
      </p>
    </div>
  );
}

function QuotationPanel({ citation }: { citation: Citation }) {
  return (
    <div className="max-w-md rounded-md border bg-muted/50 p-3 text-left text-sm">
      <p className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Quote className="h-3 w-3" aria-hidden="true" /> Supporting text
      </p>
      <blockquote className="italic">"{citation.supporting_quote}"</blockquote>
    </div>
  );
}

interface HighlightResult {
  rects: ViewportRect[] | null;
  attempted: boolean;
}

function PdfPageCanvas({
  doc,
  pageNumber,
  scale,
  citation,
}: {
  doc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  citation: Citation;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [highlight, setHighlight] = useState<HighlightResult>({ rects: null, attempted: false });
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let renderTask: ReturnType<import('pdfjs-dist').PDFPageProxy['render']> | null = null;

    async function renderPage() {
      setRenderError(null);
      try {
        const page = await doc.getPage(pageNumber);
        if (cancelled) return;
        const viewport = page.getViewport({ scale });
        // PDF.js's own type declarations return `any[]` from convertToViewportPoint (it's
        // always genuinely a 2-tuple at runtime); ViewportLike narrows that for the pure,
        // unit-testable math in citation-highlight.ts.
        const highlightViewport =
          viewport as unknown as import('@/lib/citation-highlight').ViewportLike;
        const canvas = canvasRef.current;
        if (!canvas) return;
        const context = canvas.getContext('2d');
        if (!context) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;

        renderTask = page.render({ canvasContext: context, viewport, canvas });
        await renderTask.promise;
        if (cancelled) return;

        // Highlight priority (never fabricated -- see citation-highlight.ts):
        // 1. A verified parser bbox, only when the chunker marked it exact for this chunk.
        // 2. Otherwise, a text-layer match of the validator-confirmed quotation.
        // 3. Otherwise: no highlight, and the UI says so honestly.
        const provenanceForPage = citation.provenance.find((p) => p.page_no === pageNumber);
        if (citation.bbox_reliable && provenanceForPage?.bbox) {
          setHighlight({
            rects: [bboxToViewportRect(provenanceForPage.bbox, highlightViewport)],
            attempted: true,
          });
        } else if (citation.supporting_quote) {
          const textContent = await page.getTextContent();
          if (cancelled) return;
          const rects = quoteToViewportRects(
            textContent.items as unknown as import('@/lib/citation-highlight').PdfTextItem[],
            citation.supporting_quote,
            highlightViewport,
          );
          setHighlight({ rects, attempted: true });
        } else {
          setHighlight({ rects: null, attempted: true });
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof Error && error.name === 'RenderingCancelledException') return;
        setRenderError(error instanceof Error ? error.message : 'Could not render this page.');
      }
    }

    void renderPage();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [doc, pageNumber, scale, citation]);

  return (
    <div ref={containerRef} className="min-h-0 overflow-auto bg-muted/30 p-4">
      <div className="relative mx-auto w-fit">
        <canvas ref={canvasRef} className="block shadow-md" />
        {highlight.rects?.map((rect, i) => (
          <div
            key={i}
            className="pointer-events-none absolute rounded-sm bg-yellow-300/40 ring-2 ring-yellow-500/70"
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
          />
        ))}
      </div>
      {renderError && (
        <p className="mt-2 text-center text-sm text-destructive" role="alert">
          {renderError}
        </p>
      )}
      {/* The quotation is always shown once the render/highlight attempt has settled --
          not only on a highlight-match failure -- so a viewer with a successful bbox or
          text-layer highlight still satisfies "show ... the quotation" on its own, and a
          scanned/image page with no highlight at all still lets the user verify the claim. */}
      {highlight.attempted && citation.supporting_quote && (
        <div className="mx-auto mt-4 max-w-lg">
          {!highlight.rects && (
            <p className="mb-2 flex items-center justify-center gap-1.5 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Exact visual highlight unavailable on this page (e.g. a scanned/image page with no
              selectable text layer). Showing the verified supporting text instead.
            </p>
          )}
          <QuotationPanel citation={citation} />
        </div>
      )}
    </div>
  );
}

function ViewerFooter({
  citation,
  pageNumber,
  pageCount,
  scale,
  onPageChange,
  onScaleChange,
}: {
  citation: Citation;
  pageNumber: number;
  pageCount: number;
  scale: number;
  onPageChange: (page: number) => void;
  onScaleChange: (scale: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t bg-card px-4 py-2">
      <div className="flex items-center gap-1" role="group" aria-label="Page navigation">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(pageNumber - 1)}
          disabled={pageNumber <= 1}
        >
          Previous
        </Button>
        <span className="min-w-[6rem] text-center text-xs text-muted-foreground">
          Page {pageNumber} of {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(pageNumber + 1)}
          disabled={pageNumber >= pageCount}
        >
          Next
        </Button>
      </div>
      <div className="flex items-center gap-1" role="group" aria-label="Zoom">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => onScaleChange(Math.max(MIN_SCALE, scale - SCALE_STEP))}
          disabled={scale <= MIN_SCALE}
          aria-label="Zoom out"
        >
          <ZoomOut className="h-4 w-4" aria-hidden="true" />
        </Button>
        <span className="w-12 text-center text-xs text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => onScaleChange(Math.min(MAX_SCALE, scale + SCALE_STEP))}
          disabled={scale >= MAX_SCALE}
          aria-label="Zoom in"
        >
          <ZoomIn className="h-4 w-4" aria-hidden="true" />
        </Button>
        {citation.source_document_id && (
          <a
            href={api.documentSourceUrl(citation.source_document_id)}
            target="_blank"
            rel="noreferrer"
            className={cn(
              'ml-2 inline-flex h-8 items-center gap-1.5 rounded-md border border-input px-3 text-xs font-medium hover:bg-accent hover:text-accent-foreground',
            )}
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            Open source
          </a>
        )}
      </div>
    </div>
  );
}
