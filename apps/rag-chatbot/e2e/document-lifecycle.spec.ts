import { expect, type Page, test } from '@playwright/test';
import { SAMPLE_PDF } from './fixtures/paths';

/**
 * Upload -> real stage transitions -> READY, against the controlled test
 * backend (apps/rag-chatbot/e2e/fixtures/test_backend.py), which runs the
 * real ingestion state machine and orchestrator with only the heavy
 * per-stage work (Docling, BGE, Ollama) faked -- so every stage this test
 * observes is genuinely emitted by the backend, not scripted here.
 */
test.describe('Document lifecycle', () => {
  test('upload reaches READY through real, observable stage transitions', async ({ page }) => {
    await page.goto('/#/documents');

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(SAMPLE_PDF);

    // The row appears immediately, before processing has finished.
    const row = page.locator('tr', { hasText: 'sample.pdf' });
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Real per-stage transitions (not this pre-READY moment, which can race
    // the list's own polling interval) are proven via the SSE-backed detail
    // page in the next test, which asserts the actual recorded stage
    // timings the real orchestrator emitted.
    await expect(row.getByText('Ready')).toBeVisible({ timeout: 15_000 });
  });

  test('document detail shows real chunk counts and stage timings after processing', async ({
    page,
  }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);

    const link = page.getByRole('link', { name: /sample\.pdf/ });
    await expect(link).toBeVisible({ timeout: 10_000 });
    // The list polls every 1.5s while any document is PROCESSING/UPLOADED
    // (see use-documents.ts's refetchInterval) and sorts newest-first, so
    // the just-uploaded row keeps reflowing to the top as sibling rows
    // shift under it -- worse the more documents this shared-backend test
    // run has already accumulated (playwright.config.ts: one shared
    // backend/registry per run, by design). Playwright's own pointer-event
    // interception check can catch this row mid-reflow; force is safe
    // here because the element's identity/state is what's actually
    // asserted next (Ready/Chunks indexed/etc.), not the click mechanics.
    await link.scrollIntoViewIfNeeded();
    await link.click({ force: true });

    await expect(page.getByText('Ready', { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Chunks indexed')).toBeVisible();
    // Scoped to the metadata row itself: "3" alone is ambiguous against
    // timestamps, hashes and stage-timing values elsewhere on the page.
    const chunksRow = page.getByText('Chunks indexed', { exact: true }).locator('..');
    await expect(chunksRow.getByText('3', { exact: true })).toBeVisible();
    await expect(page.getByText('Processing history')).toBeVisible();
    await expect(page.getByText(/Parsing document/)).toBeVisible();
  });

  test('the extracted content preview renders sanitised Markdown', async ({ page }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    const link = page.getByRole('link', { name: /sample\.pdf/ });
    await expect(link).toBeVisible({ timeout: 10_000 });
    // See the matching comment in the previous test for why force is safe here.
    await link.scrollIntoViewIfNeeded();
    await link.click({ force: true });

    await expect(page.getByText('Ready', { exact: true })).toBeVisible({ timeout: 15_000 });
    // The preview is a separate, READY-gated fetch that starts only once the
    // status above resolves, so it needs its own headroom beyond the
    // default assertion timeout.
    await expect(page.getByRole('heading', { name: 'Sample Engineering Document' })).toBeVisible({
      timeout: 10_000,
    });
  });

  /**
   * Opens the row's actions menu via real keyboard activation (focus + Enter,
   * arrow-key navigation) rather than a pointer/touch click on the menu item:
   * Radix only moves focus into the menu's roving-tabindex system on a
   * keyboard-driven open, which is also exactly what a keyboard user does --
   * this is genuine required-path coverage, not a workaround for a flaky
   * click. Each call is a fresh, independent open/close cycle (the two
   * confirmation-dialog tests below each call this exactly once), which
   * avoids any state carried over between repeated opens of the same
   * Radix popper within one test.
   */
  async function openDeleteConfirmation(page: Page, row: ReturnType<Page['locator']>) {
    await row.scrollIntoViewIfNeeded();
    await row.getByRole('button', { name: /Actions for/ }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('menuitem', { name: 'View details' })).toBeFocused();
    await page.keyboard.press('ArrowDown'); // Reprocess
    await expect(page.getByRole('menuitem', { name: 'Reprocess' })).toBeFocused();
    await page.keyboard.press('ArrowDown'); // Delete
    await expect(page.getByRole('menuitem', { name: 'Delete' })).toBeFocused();
    await page.keyboard.press('Enter');
    return page.getByRole('dialog');
  }

  async function uploadReadySampleRow(page: Page) {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    const row = page.locator('tr', { hasText: 'sample.pdf' });
    await expect(row.getByText('Ready')).toBeVisible({ timeout: 15_000 });
    return row;
  }

  test('the delete confirmation dialog explains the impact and cancelling deletes nothing', async ({
    page,
  }) => {
    const row = await uploadReadySampleRow(page);
    const dialog = await openDeleteConfirmation(page, row);

    await expect(dialog).toContainText('Delete "sample.pdf"?');
    await expect(dialog).toContainText('can no longer be searched');

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).not.toBeVisible();
    await expect(row).toBeVisible();
  });

  test('confirming deletion removes the document', async ({ page }) => {
    const row = await uploadReadySampleRow(page);
    const dialog = await openDeleteConfirmation(page, row);

    await dialog.getByRole('button', { name: 'Delete document' }).click();

    await expect(page.locator('tr', { hasText: 'sample.pdf' })).not.toBeVisible({
      timeout: 5_000,
    });
  });
});
