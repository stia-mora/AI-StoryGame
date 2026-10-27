import { PL_PAGE_IDS, PL_HASH_ALIASES } from "../../router.js";
// nextTarget.js — resolve post-login redirect target.
// Validate browser-normalized same-origin routes before navigating.

export function __resolveNextOrDefault(user) {
  const player = user?.account_mode === 'player' && user?.role !== 'admin';
  const fallback = '/play';
  try {
    const values = new URLSearchParams(location.search).getAll('next');
    if (values.length !== 1) return fallback;
    const raw = values[0];
    if (!raw || /[\\\u0000-\u0020\u007f]/.test(raw)) return fallback;
    const target = new URL(raw, location.origin);
    if (!['http:', 'https:'].includes(target.protocol) || target.origin !== location.origin) return fallback;
    const play = /^\/play(?:\/(?:saves(?:\/\d+)?|stories\/\d+(?:\/comments)?|wallet|manage))?\/?$/.test(target.pathname) || target.pathname === '/Player.html';
    const page = target.pathname.replace(/^\/|\/$/g, '');
    const creator = page === 'Platform.html' || PL_PAGE_IDS.includes(PL_HASH_ALIASES[page] || page)
      || ['/play/authoring', '/play/authoring-admin', '/oauth/authoring/authorize'].includes(target.pathname);
    if (!play && (player || !creator)) return fallback;
    return target.pathname + target.search + target.hash;
  } catch (_) { return fallback; }
}
