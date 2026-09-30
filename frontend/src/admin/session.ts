import type { LoginResponse } from '../types';

export type AdminSession = Pick<LoginResponse, 'access_token' | 'expires_at'>;
const storageKey = 'livemap.admin.session';
export const sessionRejectedEvent = 'livemap:admin-session-rejected';

export function saveSession(session: AdminSession | null): void {
  try {
    if (session) window.sessionStorage.setItem(storageKey, JSON.stringify(session));
    else window.sessionStorage.removeItem(storageKey);
  } catch {
    // Storage may be disabled; the current in-memory session can still be used.
  }
}

export function readSession(): AdminSession | null {
  try {
    const session = JSON.parse(window.sessionStorage.getItem(storageKey) ?? 'null');
    if (session && typeof session.access_token === 'string' && session.access_token
      && typeof session.expires_at === 'string' && Date.parse(session.expires_at) > Date.now()) {
      return { access_token: session.access_token, expires_at: session.expires_at };
    }
  } catch {
    // Invalid or unavailable storage must not prevent the login form from opening.
  }
  saveSession(null);
  return null;
}
