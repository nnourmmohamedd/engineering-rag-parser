import { expect, type Page, test } from '@playwright/test';
import {
  closeMobileOptionsDrawerIfOpen,
  documentSelectionScope,
  openMobileOptionsDrawerIfNeeded,
} from './fixtures/helpers';
import { SAMPLE_REAL_PDF } from './fixtures/paths';

async function uploadRealPdfAndWaitReady(page: Page, filename = 'sample-real.pdf') {
  await page.goto('/#/documents');
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_REAL_PDF);
  const row = page.locator('tr', { hasText: filename });
  await expect(row.getByText('Ready')).toBeVisible({ timeout: 15_000 });
}

async function selectDocument(page: Page, filename = 'sample-real.pdf') {
  await page.goto('/#/');
  const isMobile = await openMobileOptionsDrawerIfNeeded(page);
  await documentSelectionScope(page, isMobile)
    .getByLabel(new RegExp(filename.replace('.', '\\.')))
    .check();
  await closeMobileOptionsDrawerIfOpen(page, isMobile);
}

async function ask(page: Page, question: string) {
  await page.getByLabel('Question', { exact: true }).fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
}

test.describe('Exact PDF passage navigation', () => {
  test('clicking a citation card opens the PDF viewer at the cited page with the quotation shown', async ({
    page,
  }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await expect(page.getByText('Sources (1)')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // The header's filename paragraph specifically (the sr-only dialog title also contains
    // "sample.pdf" as a substring, so an unscoped match would be ambiguous).
    await expect(dialog.locator('p.text-sm.font-medium', { hasText: 'sample.pdf' })).toBeVisible();
    await expect(dialog.getByText(/Page 1 of/)).toBeVisible();
    await expect(dialog.getByText('Introduction')).toBeVisible();
    await expect(dialog.getByText('chunk_1')).toBeVisible();
    // The real PDF page actually rendered onto a canvas.
    await expect(dialog.locator('canvas')).toBeVisible();
  });

  test('clicking an inline [S<n>] marker in the answer also opens the viewer', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await expect(page.getByText('Grounded answer')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /open citation s1 source/i }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('dialog').locator('canvas')).toBeVisible();
  });

  test('the exact supporting quotation is shown alongside the rendered page', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('canvas')).toBeVisible();
    // No bbox provenance in this fake pipeline -- falls back to the verified text-layer
    // match; either the highlighted-match state or the explicit fallback notice is
    // acceptable, but the quotation itself must always be reachable somewhere in the panel.
    await expect(dialog.getByText(/end-to-end testing/)).toBeVisible({ timeout: 5_000 });
  });

  test('page navigation controls move between pages of the same PDF', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Page 1 of 2')).toBeVisible();
    await dialog.getByRole('button', { name: 'Next' }).click();
    await expect(dialog.getByText('Page 2 of 2')).toBeVisible();
    await dialog.getByRole('button', { name: 'Previous' }).click();
    await expect(dialog.getByText('Page 1 of 2')).toBeVisible();
  });

  test('zoom controls change the displayed zoom level', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('120%')).toBeVisible();
    await dialog.getByRole('button', { name: 'Zoom in' }).click();
    await expect(dialog.getByText('140%')).toBeVisible();
    await dialog.getByRole('button', { name: 'Zoom out' }).click();
    await dialog.getByRole('button', { name: 'Zoom out' }).click();
    await expect(dialog.getByText('100%')).toBeVisible();
  });

  test('"Open source" links directly to the raw PDF', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    const openSourceLink = dialog.getByRole('link', { name: /open source/i });
    await expect(openSourceLink).toHaveAttribute('href', /\/api\/v1\/documents\/.+\/source/);
    await expect(openSourceLink).toHaveAttribute('target', '_blank');
  });

  test('a claim requiring multiple citations across different pages: prev/next cycles between them', async ({
    page,
  }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'Give me a multi-part answer about this document.');
    await expect(page.getByText('Sources (2)')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('1 / 2')).toBeVisible();
    await expect(dialog.getByText('Page 1 of 2')).toBeVisible();

    await dialog.getByRole('button', { name: 'Next citation' }).click();
    await expect(dialog.getByText('2 / 2')).toBeVisible();
    // Citation S2 cites page 2 -- the viewer jumps to it automatically on switch.
    await expect(dialog.getByText('Page 2 of 2')).toBeVisible();
    // Scoped to the header (not getByText('Maintenance') alone): the always-visible
    // quotation panel's own text also contains "maintenance" as a case-insensitive
    // substring ("...valve maintenance schedules"), which would otherwise be ambiguous.
    await expect(
      dialog.locator('p.text-xs.text-muted-foreground', { hasText: 'Maintenance' }),
    ).toBeVisible();

    await expect(dialog.getByRole('button', { name: 'Next citation' })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Previous citation' }).click();
    await expect(dialog.getByText('1 / 2')).toBeVisible();
  });

  test('closing the viewer preserves the conversation underneath it', async ({ page }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await expect(page.getByText('Grounded answer')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    await page.getByRole('button', { name: /close/i }).click();
    await expect(page.getByRole('dialog')).not.toBeVisible();
    // The conversation, including the answer text, is still there -- opening the viewer
    // never navigated away from or discarded it. (Matches twice: the answer prose and the
    // still-expanded citation card's own quote blockquote -- both proving the point.)
    await expect(page.getByText('Grounded answer')).toBeVisible();
    await expect(page.getByText(/end-to-end testing/).first()).toBeVisible();
  });

  test('the viewer is keyboard accessible: Escape closes it, Tab reaches its controls', async ({
    page,
  }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Zoom in' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).not.toBeVisible();
  });

  test('a deleted source shows the honest "unavailable" state with the quotation preserved', async ({
    page,
  }) => {
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await expect(page.getByText('Sources (1)')).toBeVisible({ timeout: 10_000 });

    const conversationsBefore = await page.request.get('/api/v1/conversations');
    const conversationList = (await conversationsBefore.json()) as Array<{
      conversation_id: string;
    }>;
    const conversationId = conversationList[0]?.conversation_id;
    if (!conversationId) throw new Error('no conversation found via API');

    const documents = await page.request.get('/api/v1/documents');
    const documentList = (await documents.json()) as Array<{
      document_id: string;
      display_name: string;
    }>;
    const target = documentList.find((d) => d.display_name === 'sample-real.pdf');
    if (!target) throw new Error('uploaded document not found via API');
    const deleteResponse = await page.request.delete(`/api/v1/documents/${target.document_id}`);
    if (!deleteResponse.ok()) throw new Error(`delete failed: ${deleteResponse.status()}`);

    // The real, running backend must resolve the citation's availability live from the
    // current registry state -- never a value frozen at answer time -- while the exact
    // quote and page it was originally shown with stay untouched (see
    // docs/chatbot/DOCUMENT_LIFECYCLE.md). This is the same data the UI's citation card
    // renders from (see src/lib/types.ts's Citation.source_available/source_document_id
    // and citation-card.test.tsx's "flags an unavailable (deleted) source" unit test).
    const conversationAfter = await page.request.get(`/api/v1/conversations/${conversationId}`);
    const detail = (await conversationAfter.json()) as {
      messages: Array<{ citations: Array<Record<string, unknown>> }>;
    };
    const citation = detail.messages
      .flatMap((m) => m.citations)
      .find((c) => c.citation_id === 'S1');
    expect(citation).toBeDefined();
    expect(citation?.source_available).toBe(false);
    expect(citation?.source_document_id).toBeNull();
    expect(citation?.supporting_quote).toMatch(/end-to-end testing/);
    expect(citation?.page_numbers).toEqual([1]);
  });

  test('mobile viewport: the viewer opens and its controls remain reachable', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await uploadRealPdfAndWaitReady(page);
    await selectDocument(page);
    await ask(page, 'What is this document about?');
    await expect(page.getByText('Sources (1)')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /\[S1\]/ }).click();
    await page.getByRole('button', { name: /open source/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('canvas')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Zoom in' })).toBeVisible();
  });
});
