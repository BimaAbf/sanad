/**
 * The client curriculum against the server seed.
 *
 * `src/content/curriculum.ts` and `services/api/seeds/curriculum.py` both list
 * the 88 skills. Two lists drift, and the way this pair drifts is silent: a code
 * renamed in the seed does not break a build, it makes one activity in a
 * session render a blank card, in a language most of the people reading the
 * diff cannot check.
 *
 * So this parses the Python and compares. It is the same trick
 * `src/tokens.test.ts` uses against docs/06, and for the same reason — the
 * other file is the source of truth, and a test is the only thing that keeps
 * that true.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  CATEGORY_ORDER,
  REVIEWED_BY,
  SKILLS,
  skill,
  skillsIn,
  type SkillCategory,
} from "@/content/curriculum";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..", "..");
const SEED = join(REPO_ROOT, "services", "api", "seeds", "curriculum.py");

/** The first string in each tuple of a named block in the seed. */
function firstFieldOf(block: string): string[] {
  const source = readFileSync(SEED, "utf8");
  const start = source.indexOf(`${block}:`);
  expect(start, `${block} not found in the seed`).toBeGreaterThan(-1);
  const open = source.indexOf("= (", start) + 3;
  const close = source.indexOf("\n)", open);
  return [...source.slice(open, close).matchAll(/\(\s*"([^"]+)"/g)].map(
    (match) => match[1]!,
  );
}

describe("the curriculum matches the API seed", () => {
  const expected: Array<[SkillCategory, string, string[]]> = [
    ["colors", "color_", firstFieldOf("COLOURS")],
    ["body_parts", "body_", firstFieldOf("BODY_PARTS")],
    ["social", "social_", firstFieldOf("SOCIAL")],
    ["household", "hh_", firstFieldOf("HOUSEHOLD")],
    ["numbers", "num_", firstFieldOf("NUMERALS")],
    ["letters", "letter_", firstFieldOf("LETTERS")],
  ];

  for (const [category, prefix, suffixes] of expected) {
    it(`${category} has the seed's codes, in the seed's order`, () => {
      expect(skillsIn(category).map((item) => item.code)).toEqual(
        suffixes.map((suffix) => `${prefix}${suffix}`),
      );
    });
  }

  it("is 88 skills", () => {
    // docs/04c §C05 says 88 and every other count in the product is derived
    // from it, including the caregiver's skill map.
    expect(SKILLS).toHaveLength(88);
  });

  it("introduces categories in the seed's order", () => {
    const seen: SkillCategory[] = [];
    for (const item of SKILLS) {
      if (seen[seen.length - 1] !== item.category) seen.push(item.category);
    }
    expect(seen).toEqual([...CATEGORY_ORDER]);
  });
});

describe("every skill is renderable", () => {
  it("has a unique code", () => {
    expect(new Set(SKILLS.map((item) => item.code)).size).toBe(SKILLS.length);
  });

  it("has a contiguous introduction order starting at zero", () => {
    // The adaptive engine schedules against `intro_order`. A gap or a duplicate
    // is a skill that is either introduced twice or never.
    expect(SKILLS.map((item) => item.introOrder)).toEqual(
      SKILLS.map((_, index) => index),
    );
  });

  it("has a label and Arabic alt text", () => {
    // docs/06 §5 makes alt text a mandatory column, not a nicety: it is the
    // only channel a caregiver's screen reader has for a picture.
    const missing = SKILLS.filter((item) => !item.labelAr.trim() || !item.altAr.trim());
    expect(missing.map((item) => item.code)).toEqual([]);
  });

  it("gives every colour a hex and every number a count", () => {
    expect(skillsIn("colors").filter((item) => !item.hex)).toEqual([]);
    expect(skillsIn("numbers").filter((item) => !item.count)).toEqual([]);
    expect(skillsIn("numbers").map((item) => item.count)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    ]);
  });

  it("gives every letter a keyword", () => {
    expect(skillsIn("letters").filter((item) => !item.keywordAr)).toEqual([]);
  });

  it("speaks a word for a glyph rather than the glyph", () => {
    // "وريني ٣" is a sentence no adult says to a child. The written label is
    // the numeral; the spoken one is the word.
    expect(skill("num_3")?.labelAr).toBe("٣");
    expect(skill("num_3")?.labelEgy).toBe("تلاتة");
  });
});

describe("the review gate", () => {
  it("is still open", () => {
    // This file's Arabic is agent-written and unreviewed. When a native speaker
    // has signed it off, REVIEWED_BY carries their name and this test is
    // rewritten to assert that it is non-empty — not deleted. Failing here is
    // the reminder that the assertion has not been flipped yet.
    expect(REVIEWED_BY).toBe("");
  });
});
