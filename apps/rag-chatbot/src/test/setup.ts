import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => cleanup());

// jsdom has no matchMedia; the theme hook and any responsive logic need it.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

// jsdom has no EventSource; hooks that open one need a controllable stand-in.
class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    this.readyState = 2;
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

// @ts-expect-error -- test-only global stand-in
window.EventSource = MockEventSource;
// @ts-expect-error -- exposed for tests to reach the latest instance
window.__MockEventSource = MockEventSource;

// jsdom has no DOMMatrix; pdfjs-dist's canvas backend references it at module-load time
// (feature detection), even in tests that never actually render a PDF page. A minimal
// stand-in is enough -- component tests mock `fetch` to fail before any real PDF loads,
// so this is never asked to do real matrix math.
if (!window.DOMMatrix) {
  class MockDOMMatrix {
    a = 1;
    b = 0;
    c = 0;
    d = 1;
    e = 0;
    f = 0;
  }
  // @ts-expect-error -- test-only global stand-in, not a full DOMMatrix implementation
  window.DOMMatrix = MockDOMMatrix;
}
