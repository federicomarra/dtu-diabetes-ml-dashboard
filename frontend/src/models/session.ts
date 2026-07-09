/**
 * Patient "session" — an external_id parked in localStorage. There is no password;
 * these keys are the only login state the app has.
 *
 * The saved ID can go stale (DB reset, patient deleted), so every redirect that trusts
 * it must be able to undo it — otherwise the user is bounced to "Patient Not Found"
 * forever and can never reach the login form again.
 */

const ID_KEY = "logged_in_patient_id";
const NAME_KEY = "logged_in_patient_name";

export function getSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ID_KEY);
}

export function saveSession(externalId: string, name: string): void {
  localStorage.setItem(ID_KEY, externalId);
  localStorage.setItem(NAME_KEY, name);
  window.dispatchEvent(new Event("storage"));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ID_KEY);
  localStorage.removeItem(NAME_KEY);
  window.dispatchEvent(new Event("storage"));
}
