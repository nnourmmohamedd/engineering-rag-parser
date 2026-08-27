import { expect, test } from '@playwright/test';
import { documentSelectionScope, openMobileOptionsDrawerIfNeeded } from './fixtures/helpers';
import { SAMPLE_PDF } from './fixtures/paths';

test.describe('Mobile layout', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the mobile navigation drawer opens and closes without horizontal overflow', async ({
    page,
  }) => {
    await page.goto('/#/');

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1); // +1 for sub-pixel rounding

    await page.getByRole('button', { name: 'Open navigation menu' }).click();
    await expect(page.getByRole('link', { name: 'Documents' })).toBeVisible();
    await page.getByRole('button', { name: 'Close navigation menu' }).click();
  });

  test('the documents page table scrolls horizontally inside its own container, not the page', async ({
    page,
  }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    await expect(page.locator('tr', { hasText: 'sample.pdf' })).toBeVisible({ timeout: 10_000 });

    // `scrollWidth` alone is not a reliable proxy here: a fixed-position,
    // 1x1px aria-live announcer element (rendered off-screen by the toast
    // library, by design, for screen readers) can inflate it even though
    // `body { overflow-x: hidden }` genuinely prevents the page from
    // scrolling. What actually matters -- and what a user could ever
    // perceive -- is whether the viewport can be scrolled horizontally, so
    // assert that directly.
    const before = await page.evaluate(() => window.scrollX);
    await page.mouse.wheel(500, 0);
    await page.waitForTimeout(150);
    const after = await page.evaluate(() => window.scrollX);
    expect(after).toBe(before);
  });

  test('the chat options (document selection) drawer is reachable on mobile', async ({ page }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    await expect(page.locator('tr', { hasText: 'sample.pdf' }).getByText('Ready')).toBeVisible({
      timeout: 15_000,
    });

    await page.goto('/#/');
    await page
      .getByRole('button', { name: 'Open document selection and retrieval options' })
      .click();
    // Scoped to the open drawer: the (CSS-hidden) desktop panel is also
    // mounted and would otherwise make this locator ambiguous.
    const drawer = page.getByRole('dialog', { name: 'Documents & retrieval' });
    await expect(drawer.getByLabel(/sample\.pdf/)).toBeVisible();
  });
});

test.describe('Retrieval modes', () => {
  test('all four retrieval modes are selectable and reach the backend', async ({ page }) => {
    await page.goto('/#/documents');
    await page.locator('input[type="file"]').setInputFiles(SAMPLE_PDF);
    await expect(page.locator('tr', { hasText: 'sample.pdf' }).getByText('Ready')).toBeVisible({
      timeout: 15_000,
    });

    await page.goto('/#/');
    const isMobile = await openMobileOptionsDrawerIfNeeded(page);
    const scope = documentSelectionScope(page, isMobile);

    await scope.getByLabel(/sample\.pdf/).check();

    for (const mode of ['Hybrid', 'Vector + Rerank', 'Hybrid + Rerank', 'Vector']) {
      await scope.getByLabel('Retrieval mode').click();
      // The open <Select> options render in a portal, outside the drawer.
      await page.getByRole('option', { name: mode, exact: true }).click();
      await expect(scope.getByLabel('Retrieval mode')).toContainText(mode);
    }
  });
});
