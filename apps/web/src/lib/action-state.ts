/**
 * The shape a form action hands back to its form.
 *
 * Its own module because a `"use server"` file may export nothing but async
 * functions - a plain `const` there is a runtime error ("can only export async
 * functions, found object"), and one the production build does not catch.
 */
export interface ActionState {
  ok: boolean;
  /** Arabic, straight from the API when the API sent Arabic. */
  error: string | null;
}

export const EMPTY_STATE: ActionState = { ok: false, error: null };
