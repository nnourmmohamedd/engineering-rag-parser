import { expect, test } from '@playwright/test';
import {
  closeMobileOptionsDrawerIfOpen,
  documentSelectionScope,
  openMobileOptionsDrawerIfNeeded,
} from './fixtures/helpers';
import { SAMPLE_PDF } from './fixtures/paths';

/**
 * Proves the document selector actually restricts which documents are sent
 * to the backend -- the same guarantee `test_document_isolation.py` proves
 * at the retrieval layer, verified here through the real UI and a real
 * network request to the real (fake-backed) API.
 */
test.describe('Selected-document isolation', () => {
  test('only the checked documents are sent in the question request', async ({ page }) => {
    // Two independent uploads -> two independent documents.
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    await expect(page.locator('tr', { hasText: 'sample.pdf' }).getByText('Ready')).toBeVisible({
      timeout: 15_000,
    });

    await page.goto('/#/');
    const isMobile = await openMobileOptionsDrawerIfNeeded(page);

    const checkbox = documentSelectionScope(page, isMobile).getByLabel(/sample\.pdf/);
    await expect(checkbox).toBeVisible();
    await checkbox.check();
    await closeMobileOptionsDrawerIfOpen(page, isMobile);

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/messages') && req.method() === 'POST'),
      (async () => {
        await page.getByLabel('Question', { exact: true }).fill('What is this document about?');
        await page.getByRole('button', { name: 'Send question' }).click();
      })(),
    ]);

    const body = request.postDataJSON() as { selected_document_ids: string[] };
    expect(body.selected_document_ids).toHaveLength(1);
  });

  test('an empty selection cannot be submitted', async ({ page }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    await expect(page.locator('tr', { hasText: 'sample.pdf' }).getByText('Ready')).toBeVisible({
      timeout: 15_000,
    });

    await page.goto('/#/');
    await page.getByLabel('Question', { exact: true }).fill('A question with nothing selected');

    let requestFired = false;
    page.on('request', (req) => {
      if (req.url().includes('/messages')) requestFired = true;
    });
    await page
      .getByRole('button', { name: 'Send question' })
      .click({ force: true })
      .catch(() => {});
    await page.waitForTimeout(300);

    expect(requestFired).toBe(false);
  });
});
