import { CATEGORY_ORDER, skillsIn, type SkillCategory } from "@/content/curriculum";

/**
 * A "world" is a curriculum category with a face on it.
 *
 * The six `skill_category` values are a database enum; they are also the six
 * things a parent chooses between on the start screen and the six sections of
 * the skill map. Which drawing represents each one has to be the same in all
 * three places, or the tile a caregiver taps in `/play` is not the tile they
 * recognise in `/child/…/skills`.
 *
 * Deliberately not in `scenes.tsx`, where this began: that file is `"use
 * client"`, and importing it from the server-rendered landing page would drag a
 * client boundary across a page that has no interactivity on it at all.
 */

export interface World {
  category: SkillCategory;
  /** The skill whose drawing stands for the whole world. */
  faceCode: string;
  /** A pale ground that clears 7:1 against `--c-ink`. */
  tint: string;
  count: number;
}

/** Chosen to be recognisable at 48 px, which is the smallest they are drawn. */
const FACE: Record<SkillCategory, string> = {
  colors: "color_red",
  body_parts: "body_hand",
  social: "social_good_morning",
  household: "hh_cup",
  numbers: "num_3",
  letters: "letter_alef",
};

const TINT: Record<SkillCategory, string> = {
  colors: "#FDF0E4",
  body_parts: "#E4F2EE",
  social: "#EDE9F7",
  household: "#E6F0FA",
  numbers: "#FDF0E4",
  letters: "#E4F2EE",
};

export const WORLDS: readonly World[] = CATEGORY_ORDER.map((category) => ({
  category,
  faceCode: FACE[category],
  tint: TINT[category],
  count: skillsIn(category).length,
}));

export function world(category: SkillCategory): World {
  return WORLDS.find((item) => item.category === category)!;
}
