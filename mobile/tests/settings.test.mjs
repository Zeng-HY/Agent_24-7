import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeOrigin, entryUrl } from '../src/settings.mjs';
test('HTTPS origin supports current IP, future domain and port', () => {
  assert.equal(normalizeOrigin(' https://8.166.15.235/ '), 'https://8.166.15.235');
  assert.equal(entryUrl('https://pocketagentdesk.com:8443', 'account'), 'https://pocketagentdesk.com:8443/account');
  assert.equal(entryUrl('https://example.com', 'home'), 'https://example.com/');
});
test('reject insecure, credential-bearing and non-origin addresses', () => {
  for (const value of ['http://example.com', 'javascript:alert(1)', 'https://user:pass@example.com', 'https://example.com/account', 'https://example.com/?token=abc', 'https://example.com/#invite=abc', 'https://example.com/?', 'https://example.com/#', 'https://example.com\\evil', 'https://exam\nple.com']) {
    assert.throws(() => normalizeOrigin(value), undefined, value);
  }
  assert.throws(() => entryUrl('https://example.com', '//evil.com'));
});
