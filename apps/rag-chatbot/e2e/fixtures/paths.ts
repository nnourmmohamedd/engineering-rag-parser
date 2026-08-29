import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const SAMPLE_PDF = path.join(__dirname, 'sample.pdf');

/** A real, structurally valid, 2-page PDF (generated with reportlab) -- unlike
 * `sample.pdf` (a minimal signature-only stub), PDF.js can actually open and render
 * this one, so it's used by the citation-navigation E2E tests. Page 1 contains the
 * exact text the fake backend's citation quotes; page 2 has unrelated content. */
export const SAMPLE_REAL_PDF = path.join(__dirname, 'sample-real.pdf');
