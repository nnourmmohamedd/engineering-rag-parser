import { expect, type Page, test } from '@playwright/test';
import {
  closeMobileOptionsDrawerIfOpen,
  documentSelectionScope,
  openMobileOptionsDrawerIfNeeded,
} from './fixtures/helpers';
import { SAMPLE_PDF } from './fixtures/paths';

async function uploadAndWaitReady(page: Page, filename = 'sample.pdf') {
  await page.goto('/#/documents');
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
  const row = page.locator('tr', { hasText: filename });
  await expect(row.getByText('Ready')).toBeVisible({ timeout: 15_000 });
}

async function selectSampleDocument(page: Page) {
  await page.goto('/#/');
  const isMobile = await openMobileOptionsDrawerIfNeeded(page);
  await documentSelectionScope(page, isMobile)
    .getByLabel(/sample\.pdf/)
    .check();
  await closeMobileOptionsDrawerIfOpen(page, isMobile);
}

test.describe('Chat: grounded answers and citations', () => {
  test('select a document, ask a question, receive a grounded answer with a citation', async ({
    page,
  }) => {
    await uploadAndWaitReady(page);
    await selectSampleDocument(page);

    await page.getByLabel('Question', { exact: true }).fill('What is this document about?');
    await page.getByRole('button', { name: 'Send question' }).click();

    await expect(page.getByText('Grounded answer')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/end-to-end testing/)).toBeVisible();
    await expect(page.getByText('Sources (1)')).toBeVisible();
  });

  test('opening a citation reveals its page and source information', async ({ page }) => {
    await uploadAndWaitReady(page);
    await selectSampleDocument(page);

    await page.getByLabel('Question', { exact: true }).fill('What is this document about?');
    await page.getByRole('button', { name: 'Send question' }).click();
    await expect(page.getByText('Sources (1)')).toBeVisible({ timeout: 10_000 });

    // The collapsed trigger already shows the source filename and page.
    await expect(page.getByRole('button', { name: '[S1] sample.pdf · p.1' })).toBeVisible();
    await page.getByRole('button', { name: /\[S1\]/ }).click();
    // Scoped to the expanded citation panel: "sample.pdf" also appears in
    // the (still-visible) document selector's checkbox label.
    const panel = page.locator('#citation-panel-S1');
    await expect(panel).toBeVisible();
    await expect(panel.getByText('Introduction')).toBeVisible();
    await expect(panel.getByText('chunk_1')).toBeVisible();
    await expect(panel.getByText(/end-to-end testing/)).toBeVisible();
  });

  test('a question containing no supported evidence is explicitly refused', async ({ page }) => {
    await uploadAndWaitReady(page);
    await selectSampleDocument(page);

    await page
      .getByLabel('Question', { exact: true })
      .fill('This is an unsupported question about aliens.');
    await page.getByRole('button', { name: 'Send question' }).click();

    await expect(page.getByText(/Insufficient evidence/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/could not find enough evidence/)).toBeVisible();
    // A refusal must never present fabricated sources.
    await expect(page.getByText(/Sources \(/)).not.toBeVisible();
  });

  test('the send button is disabled until a document is selected', async ({ page }) => {
    await uploadAndWaitReady(page);
    await page.goto('/#/');

    await page.getByLabel('Question', { exact: true }).fill('Any question');
    await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
    await expect(page.getByText(/Select at least one document/)).toBeVisible();
  });
});
