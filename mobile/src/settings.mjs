export const DEFAULT_ORIGIN = 'https://8.166.15.235';
export function normalizeOrigin(value) {
  const text = value.trim();
  let url;
  try { url = new URL(text); } catch { throw new Error('请输入完整的 HTTPS 服务地址。'); }
  if (url.protocol !== 'https:' || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash || /[\\\s]/.test(text) ||
      text.includes('?') || text.includes('#')) {
    throw new Error('只填写 HTTPS 地址和可选端口，不含账号、路径、参数或配对码。');
  }
  return url.origin;
}
export function entryUrl(origin, entry) {
  if (!['home', 'account'].includes(entry)) throw new Error('入口无效。');
  return normalizeOrigin(origin) + (entry === 'account' ? '/account' : '/');
}
