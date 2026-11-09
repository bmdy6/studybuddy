import { getStoredToken } from './token';

export function shouldClearStoredAuth(status: number | undefined, requestToken: string | null | undefined) {
  if (status !== 401 || !requestToken) return false;
  return getStoredToken() === requestToken;
}

export function clearStoredAuth(status: number | undefined, requestToken: string | null | undefined) {
  if (!shouldClearStoredAuth(status, requestToken)) return false;
  localStorage.removeItem('studybuddy-auth');
  return true;
}

export function redirectToLoginIfNeeded() {
  if (window.location.hash !== '#/login') {
    window.location.hash = '#/login';
  }
}
