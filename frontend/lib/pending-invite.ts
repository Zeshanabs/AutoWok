// Remembers an invitation link while the person signs in or registers, so they
// land back on the invitation afterwards instead of the dashboard.

const KEY = "autowok.pendingInvite";
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{20,200}$/;

export function rememberInvite(token: string): void {
  try {
    if (TOKEN_PATTERN.test(token)) window.sessionStorage.setItem(KEY, token);
  } catch {
    // Storage can be unavailable (private mode); the link still works when reopened.
  }
}

export function forgetInvite(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clean up.
  }
}

/** Where to go after signing in: the pending invitation if there is one, otherwise the dashboard. */
export function pathAfterSignIn(): string {
  try {
    const token = window.sessionStorage.getItem(KEY);
    if (token && TOKEN_PATTERN.test(token)) return `/invite/${token}`;
  } catch {
    // Fall through to the dashboard.
  }
  return "/dashboard";
}
