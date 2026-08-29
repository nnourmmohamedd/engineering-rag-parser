/**
 * Pure, PDF.js-shaped highlight math: bbox -> viewport rectangle, and quotation ->
 * text-layer rectangles. No PDF.js import here (only the minimal shapes it hands
 * back), so this module is unit-testable without loading a real PDF.
 *
 * Coordinate convention: a bbox is `[left, top, right, bottom]` in PDF points,
 * bottom-left page origin (Docling's own convention -- see
 * `services/chunker/models.py::ProvenanceRecord`). `top` is numerically larger
 * than `bottom` (y increases upward), matching how the backend already documents it.
 */

/** The subset of PDF.js's `PageViewport` this module needs -- `convertToViewportPoint` is
 * the one still present in PDF.js v6's public API (its older `convertToViewportRectangle`
 * helper was removed upstream). */
export interface ViewportLike {
  convertToViewportPoint(x: number, y: number): [number, number];
}

export interface ViewportRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Convert one PDF-space bbox to a top-left-origin pixel rectangle for CSS overlay. */
export function bboxToViewportRect(
  bbox: readonly [number, number, number, number],
  viewport: ViewportLike,
): ViewportRect {
  const [left, top, right, bottom] = bbox;
  const [vx1, vy1] = viewport.convertToViewportPoint(left, bottom);
  const [vx2, vy2] = viewport.convertToViewportPoint(right, top);
  return {
    left: Math.min(vx1, vx2),
    top: Math.min(vy1, vy2),
    width: Math.abs(vx2 - vx1),
    height: Math.abs(vy2 - vy1),
  };
}

/** One PDF.js `TextContent` item -- only the fields this module actually reads.
 * `transform` is PDF.js's fixed 2D affine matrix: [scaleX, skewX, skewY, scaleY, translateX, translateY]. */
export interface PdfTextItem {
  str: string;
  transform: [number, number, number, number, number, number];
  width: number;
  height: number;
  hasEOL?: boolean;
}

/**
 * Deterministic normalization mirroring the backend's own
 * `services/grounding/validator.py::normalize_quote_text`: Unicode NFKC,
 * smart-quote/dash folding, whitespace collapsing, casefold. Kept in exact sync
 * so "the validator confirmed this quote is present" and "the viewer can find
 * it in the text layer" agree on what counts as a match.
 */
const PUNCT_MAP: Record<string, string> = {
  '‘': "'",
  '’': "'",
  '“': '"',
  '”': '"',
  '–': '-',
  '—': '-',
};

export function normalizeQuoteText(text: string): string {
  const folded = text.normalize('NFKC').replace(/[‘’“”–—]/g, (ch) => PUNCT_MAP[ch] ?? ch);
  return folded.replace(/\s+/g, ' ').trim().toLowerCase();
}

interface OffsetEntry {
  itemIndex: number;
  normalizedStart: number;
  normalizedEnd: number;
}

/**
 * Find every text item whose normalized text overlaps `quote`'s first match in the page's
 * concatenated, normalized text. Returns the matching item indices in order, or `null` if
 * the quote isn't present in this page's text layer at all (a legitimate outcome -- the
 * caller falls back to the honest "exact visual highlight unavailable" notice, never a
 * fabricated location).
 */
export function findQuoteItemIndices(items: PdfTextItem[], quote: string): number[] | null {
  const normalizedQuote = normalizeQuoteText(quote);
  if (!normalizedQuote) return null;

  let pageText = '';
  const offsets: OffsetEntry[] = [];
  items.forEach((item, itemIndex) => {
    const normalizedItem = normalizeQuoteText(item.str);
    if (!normalizedItem) return;
    const start = pageText.length > 0 ? pageText.length + 1 : 0;
    if (pageText.length > 0) pageText += ' ';
    pageText += normalizedItem;
    offsets.push({
      itemIndex,
      normalizedStart: start,
      normalizedEnd: start + normalizedItem.length,
    });
  });

  const matchStart = pageText.indexOf(normalizedQuote);
  if (matchStart === -1) return null;
  const matchEnd = matchStart + normalizedQuote.length;

  const matched = offsets.filter(
    (o) => o.normalizedStart < matchEnd && o.normalizedEnd > matchStart,
  );
  return matched.length > 0 ? matched.map((o) => o.itemIndex) : null;
}

/** One PDF.js text item's own bbox, in PDF space, from its `transform`/`width`/`height`. */
export function textItemBbox(item: PdfTextItem): [number, number, number, number] {
  // transform = [scaleX, skewX, skewY, scaleY, translateX, translateY]; PDF.js text items
  // are anchored at their baseline-left, and item.height already accounts for font size.
  const [, , , scaleY, translateX, translateY] = item.transform;
  const left = translateX;
  const bottom = translateY;
  const top = bottom + (scaleY !== 0 ? Math.abs(scaleY) : item.height);
  const right = left + item.width;
  return [left, top, right, bottom];
}

/** Highlight rectangles (one per matched text item, in viewport pixels) for a verified quote. */
export function quoteToViewportRects(
  items: PdfTextItem[],
  quote: string,
  viewport: ViewportLike,
): ViewportRect[] | null {
  const indices = findQuoteItemIndices(items, quote);
  if (indices === null) return null;
  return indices
    .map((i) => items[i])
    .filter((item): item is PdfTextItem => item !== undefined)
    .map((item) => bboxToViewportRect(textItemBbox(item), viewport));
}
