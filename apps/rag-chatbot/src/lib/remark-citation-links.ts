import { findAndReplace } from 'mdast-util-find-and-replace';
import type { Root } from 'mdast';

/**
 * Turns every literal `[S<n>]` inline citation marker in the answer text into a real
 * markdown link node (`href="#citation-S<n>"`), so it round-trips through
 * `rehype-sanitize`'s default schema (fragment hrefs are always allowed) and can be
 * rendered as a clickable element by overriding react-markdown's `a` component --
 * without weakening sanitization or introducing raw HTML.
 */
const CITATION_MARKER = /\[S(\d+)\]/g;

export function remarkCitationLinks() {
  return (tree: Root) => {
    findAndReplace(tree, [
      CITATION_MARKER,
      (_match: string, id: string) => ({
        type: 'link',
        url: `#citation-S${id}`,
        children: [{ type: 'text', value: `[S${id}]` }],
      }),
    ]);
  };
}
