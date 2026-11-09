import { beforeEach, describe, expect, it } from 'vitest';
import { clearStoredAuth, shouldClearStoredAuth } from '@/shared/api/authSession';

function persistToken(token: string) {
  localStorage.setItem(
    'studybuddy-auth',
    JSON.stringify({
      state: { token },
      version: 0,
    }),
  );
}

describe('auth session clearing', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('keeps long-lived login when a 401 belongs to a request without the current token', () => {
    persistToken('current-token');

    expect(shouldClearStoredAuth(401, null)).toBe(false);
    expect(shouldClearStoredAuth(401, 'old-token')).toBe(false);
    expect(localStorage.getItem('studybuddy-auth')).not.toBeNull();
  });

  it('clears login only when the current token is rejected as unauthorized', () => {
    persistToken('current-token');

    expect(shouldClearStoredAuth(401, 'current-token')).toBe(true);

    clearStoredAuth(401, 'current-token');

    expect(localStorage.getItem('studybuddy-auth')).toBeNull();
  });

  it('does not clear login for permission errors', () => {
    persistToken('current-token');

    expect(shouldClearStoredAuth(403, 'current-token')).toBe(false);

    clearStoredAuth(403, 'current-token');

    expect(localStorage.getItem('studybuddy-auth')).not.toBeNull();
  });
});
