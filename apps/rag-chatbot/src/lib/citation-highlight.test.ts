import { describe, expect, it } from 'vitest';
import {
  bboxToViewportRect,
  findQuoteItemIndices,
  normalizeQuoteText,
  quoteToViewportRects,
  textItemBbox,
  type PdfTextItem,
  type ViewportLike,
} from './citation-highlight';

/** A minimal, real PDF.js-compatible viewport: identity scale, y-flip (bottom-left -> top-left). */
function makeViewport(pageHeight: number): ViewportLike {
  return {
    convertToViewportPoint(x, y) {
      return [x, pageHeight - y];
    },
  };
}

function item(
  str: string,
  x: number,
  yBaseline: number,
  width: number,
  height: number,
): PdfTextItem {
  return { str, width, height, transform: [height, 0, 0, height, x, yBaseline] };
}

describe('bboxToViewportRect', () => {
  it('flips a bottom-left-origin PDF bbox into a top-left-origin CSS rect', () => {
    // Page is 800pt tall. bbox = [left=10, top=700, right=200, bottom=650] (Docling convention).
    const rect = bboxToViewportRect([10, 700, 200, 650], makeViewport(800));
    expect(rect.left).toBe(10);
    expect(rect.width).toBe(190);
    // top(700) is 100pt from the page top (800-700); bottom(650) is 150pt from the top.
    expect(rect.top).toBe(100);
    expect(rect.height).toBe(50);
  });

  it('never produces a negative width/height regardless of corner order', () => {
    const rect = bboxToViewportRect([200, 650, 10, 700], makeViewport(800));
    expect(rect.width).toBeGreaterThanOrEqual(0);
    expect(rect.height).toBeGreaterThanOrEqual(0);
  });
});

describe('normalizeQuoteText', () => {
  it('folds smart quotes/dashes, collapses whitespace, and casefolds', () => {
    expect(normalizeQuoteText('“Control  valves”\n regulate—flow')).toBe(
      '"control valves" regulate-flow',
    );
  });

  it('matches the backend normalize_quote_text contract for a plain ASCII quote', () => {
    expect(normalizeQuoteText('The mandate of C&I engineering.')).toBe(
      'the mandate of c&i engineering.',
    );
  });
});

describe('textItemBbox', () => {
  it('derives left/right/top/bottom from transform + width/height', () => {
    const bbox = textItemBbox(item('hello', 10, 100, 40, 12));
    expect(bbox).toEqual([10, 112, 50, 100]);
  });
});

describe('findQuoteItemIndices', () => {
  const items = [
    item('The mandate of', 10, 700, 90, 12),
    item('C&I engineering', 105, 700, 100, 12),
    item('is safety.', 10, 685, 60, 12),
    item('Unrelated line about valves.', 10, 670, 150, 12),
  ];

  it('finds a quote spanning exactly one text item', () => {
    const indices = findQuoteItemIndices(items, 'is safety.');
    expect(indices).toEqual([2]);
  });

  it('finds a quote spanning multiple text items joined across a line/word boundary', () => {
    const indices = findQuoteItemIndices(items, 'The mandate of C&I engineering');
    expect(indices).toEqual([0, 1]);
  });

  it('matches case-insensitively and across smart-punctuation differences', () => {
    const smartItems = [item('“Control valves” regulate flow.', 10, 700, 200, 12)];
    const indices = findQuoteItemIndices(smartItems, '"control VALVES" regulate flow.');
    expect(indices).toEqual([0]);
  });

  it('returns null when the quote is genuinely absent from this page (never a false match)', () => {
    const indices = findQuoteItemIndices(items, 'this text never appears on the page');
    expect(indices).toBeNull();
  });

  it('returns null for an empty/whitespace-only quote rather than matching everything', () => {
    expect(findQuoteItemIndices(items, '   ')).toBeNull();
  });
});

describe('quoteToViewportRects', () => {
  it('returns one rect per matched item, converted to viewport space', () => {
    const items = [item('Exact supporting passage.', 10, 700, 150, 12)];
    const rects = quoteToViewportRects(items, 'Exact supporting passage.', makeViewport(800));
    expect(rects).toHaveLength(1);
    const [rect] = rects ?? [];
    expect(rect).toBeDefined();
    expect(rect?.left).toBe(10);
    expect(rect?.width).toBe(150);
  });

  it('returns null (never a fabricated rect) when nothing matches', () => {
    const items = [item('Something else entirely.', 10, 700, 150, 12)];
    expect(quoteToViewportRects(items, 'not present', makeViewport(800))).toBeNull();
  });

  it('returns null for a scanned page with no text items at all', () => {
    expect(quoteToViewportRects([], 'anything', makeViewport(800))).toBeNull();
  });
});
