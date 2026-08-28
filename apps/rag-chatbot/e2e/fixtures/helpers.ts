import type { Locator, Page } from '@playwright/test';

/**
 * The chat page mounts the document selector twice simultaneously: a
 * desktop `aside` (CSS-hidden below `lg`) and, once opened, a mobile
 * drawer. Both are real DOM elements with genuinely-associated (if
 * differently-namespaced) labels, so an unscoped `page.getByLabel(...)`
 * resolves to two elements under Playwright's strict mode on any viewport
 * narrower than the `lg` breakpoint -- this scopes to whichever one is
 * actually interactable.
 */
export async function isMobileChatLayout(page: Page): Promise<boolean> {
  return page
    .locator('button:has-text("Options")')
    .isVisible()
    .catch(() => false);
}

export async function openMobileOptionsDrawerIfNeeded(page: Page): Promise<boolean> {
  const isMobile = await isMobileChatLayout(page);
  if (isMobile) {
    await page
      .getByRole('button', { name: 'Open document selection and retrieval options' })
      .click();
  }
  return isMobile;
}

export function documentSelectionScope(page: Page, isMobile: boolean): Locator {
  return isMobile ? page.getByRole('dialog', { name: 'Documents & retrieval' }) : page;
}

export async function closeMobileOptionsDrawerIfOpen(page: Page, isMobile: boolean): Promise<void> {
  if (isMobile) {
    // The exact aria-label, not a generic /Close/ pattern: a Sonner toast
    // left on screen from an earlier action (e.g. the upload success toast)
    // renders its own "Close toast" button, which /Close/ also matches.
    await page.getByRole('button', { name: 'Close Documents & retrieval' }).click();
  }
}
