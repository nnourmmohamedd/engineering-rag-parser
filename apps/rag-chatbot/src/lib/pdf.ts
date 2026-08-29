/**
 * PDF.js setup: local worker bundled by Vite (`?url` import), never a CDN fetch --
 * matches this application's no-remote-network posture (see `docs/chatbot/SECURITY.md`).
 */
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export { pdfjsLib };
export type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';

/** Load a PDF by URL -- PDF.js manages its own Range-request fetching against the
 * backend's `GET /documents/{id}/source` route (verified to support Range; see
 * `tests/integration/chatbot/test_api.py::TestDocumentSource::test_range_requests_are_honored`). */
export function loadPdfDocument(url: string) {
  return pdfjsLib.getDocument({ url }).promise;
}
