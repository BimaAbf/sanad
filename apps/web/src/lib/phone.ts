/**
 * Egyptian local numbers to E.164.
 *
 * `01xxxxxxxxx` is what a caregiver types and `+201xxxxxxxxx` is what the API
 * validates. Asking a parent to type a `+` is a step that exists only because
 * of our schema, so this closes the gap instead.
 *
 * Its own module, not `onboarding/actions.ts`: everything exported from a
 * `"use server"` file must be an async function, and making a pure string
 * helper into a server round-trip to satisfy that rule would be absurd.
 */
export function toE164(raw: string): string {
  const trimmed = raw.replace(/[\s-]/g, "");
  if (trimmed.startsWith("+")) return trimmed;
  if (trimmed.startsWith("00")) return `+${trimmed.slice(2)}`;
  if (trimmed.startsWith("0")) return `+20${trimmed.slice(1)}`;
  return `+${trimmed}`;
}
