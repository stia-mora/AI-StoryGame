// nextTarget.js — resolve post-login redirect target.
// Mechanically split out of login-app.jsx; body byte-for-byte unchanged.

const __DEFAULT_NEXT = 'Platform.html';

export function __resolveNextOrDefault(user) {
  if (user?.account_mode === 'player' && user?.role !== 'admin') return '/play';
  try {
    const raw = new URLSearchParams(location.search).get('next') || '';
    if (!raw) return __DEFAULT_NEXT;
    // 拒绝绝对 URL / 协议相对 URL / 包含换行的输入(开放重定向防御)
    if (/^[a-z][a-z0-9+.\-]*:|^\/\//i.test(raw) || /[\r\n]/.test(raw)) return __DEFAULT_NEXT;
    return raw;
  } catch (_) { return __DEFAULT_NEXT; }
}
