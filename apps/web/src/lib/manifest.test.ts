/**
 * The locally built session, against the rules the real one has to obey.
 *
 * These are not tests of a stand-in. `buildLocalSession` is what a child plays
 * whenever the content service cannot be reached, which docs/06 §7 says must
 * include "on a phone with no network" — so every rule the server-side planner
 * follows has to hold here too, and the ones that can be checked without a
 * child's history are checked here.
 */
import { describe, expect, it } from "vitest";

import { CATEGORY_ORDER, skill } from "@/content/curriculum";
import { instructionIsShortEnough, MAX_CHOICES } from "@/lib/interaction";
import {
  MODALITY_OF,
  buildLocalSession,
  chooseDistractors,
  correctBinKey,
  correctChoice,
} from "@/lib/manifest";

const session = buildLocalSession({ seed: 7, activityCount: 8 });

describe("shape", () => {
  it("builds the number of activities asked for", () => {
    expect(session.activities).toHaveLength(8);
  });

  it("is deterministic for a seed", () => {
    // A parent reporting "it did something odd on the third card" is only
    // actionable if that session can be rebuilt. Same seed, same session.
    expect(buildLocalSession({ seed: 7, activityCount: 8 })).toEqual(session);
  });

  it("is a different session for a different seed", () => {
    const other = buildLocalSession({ seed: 8, activityCount: 8 });
    expect(other.activities.map((a) => a.id)).not.toEqual(
      session.activities.map((a) => a.id),
    );
  });

  it("says where it came from", () => {
    // The UI never branches on this; the console needs to know how often a
    // child played bundled content instead of their planned session.
    expect(session.local).toBe(true);
  });

  it("names only real skills", () => {
    for (const activity of session.activities) {
      expect(skill(activity.skill_id), activity.skill_id).toBeDefined();
      for (const choice of activity.choices) {
        expect(skill(choice.skill_id), choice.skill_id).toBeDefined();
      }
    }
  });
});

describe("every activity is answerable and none is failable", () => {
  it("has exactly one correct choice", () => {
    for (const activity of session.activities) {
      const correct = activity.choices.filter((choice) => choice.correct);
      expect(correct, activity.id).toHaveLength(1);
      expect(correctChoice(activity)?.skill_id).toBe(activity.skill_id);
    }
  });

  it("ends its prompt ladder in an auto-selection", () => {
    // The property that makes "doing nothing" a valid answer rather than a
    // dead end. docs/06 §4.
    for (const activity of session.activities) {
      const last = activity.prompt_ladder[activity.prompt_ladder.length - 1];
      expect(last?.level, activity.id).toBe("full_model");
      expect(last?.auto_select, activity.id).toBe(true);
    }
  });

  it("keeps every instruction to five words or fewer", () => {
    // docs/06 §4. Counted after substitution, because the label is part of the
    // sentence the child hears.
    for (const activity of session.activities) {
      expect(
        instructionIsShortEnough(activity.instruction_ar, ""),
        `${activity.id}: "${activity.instruction_ar}"`,
      ).toBe(true);
    }
  });

  it("never offers more choices than the profile allows", () => {
    const wide = buildLocalSession({ seed: 3, maxChoices: 4, activityCount: 10 });
    for (const activity of wide.activities) {
      expect(activity.choices.length, activity.id).toBeLessThanOrEqual(MAX_CHOICES);
    }
  });
});

describe("the session is paced for a child, not for coverage", () => {
  it("opens on a receptive activity", () => {
    // Opening on "say the word" asks for the hardest thing in the session
    // before the child has had a single success.
    const first = session.activities[0]!;
    expect(MODALITY_OF[first.kind]).toBe("receptive");
  });

  it("never puts two expressive activities in a row", () => {
    // docs/04c §C07. Two back to back is how a child decides they are done.
    const kinds = session.activities.map((activity) => MODALITY_OF[activity.kind]);
    for (let index = 1; index < kinds.length; index += 1) {
      expect(
        kinds[index] === "expressive" && kinds[index - 1] === "expressive",
        `activities ${index - 1} and ${index}`,
      ).toBe(false);
    }
  });

  it("holds across many seeds", () => {
    for (let seed = 1; seed <= 40; seed += 1) {
      const built = buildLocalSession({ seed, activityCount: 10 });
      const kinds = built.activities.map((activity) => MODALITY_OF[activity.kind]);
      expect(kinds[0], `seed ${seed}`).toBe("receptive");
      for (let index = 1; index < kinds.length; index += 1) {
        expect(
          kinds[index] === "expressive" && kinds[index - 1] === "expressive",
          `seed ${seed}, activities ${index - 1}/${index}`,
        ).toBe(false);
      }
    }
  });
});

describe("errorless distractors", () => {
  const random = () => 0.5;

  it("never puts a same-category distractor beside a tier 1-2 skill", () => {
    // "A red card never sits beside an orange card at tier 1" — docs/04c §C05.
    // A distractor that is too similar turns a comprehension task into a
    // visual-discrimination task and manufactures a failure.
    const red = skill("color_red")!;
    expect(red.tier).toBeLessThanOrEqual(2);
    for (const distractor of chooseDistractors(red, 3, random)) {
      expect(distractor.category, distractor.code).not.toBe("colors");
    }
  });

  it("applies that rule throughout a whole session", () => {
    for (let seed = 1; seed <= 25; seed += 1) {
      for (const activity of buildLocalSession({ seed, maxChoices: 4 }).activities) {
        const target = skill(activity.skill_id)!;
        if (target.tier > 2) continue;
        for (const choice of activity.choices) {
          if (choice.correct) continue;
          expect(
            skill(choice.skill_id)!.category,
            `seed ${seed}: ${choice.skill_id} beside ${target.code}`,
          ).not.toBe(target.category);
        }
      }
    }
  });

  it("never offers the target as its own distractor", () => {
    const target = skill("hh_spoon")!;
    for (const distractor of chooseDistractors(target, 5, random)) {
      expect(distractor.code).not.toBe(target.code);
    }
  });
});

describe("the two kinds with extra structure", () => {
  const many = buildLocalSession({ seed: 11, activityCount: 24 });

  it("gives sort_category exactly two bins, one of them right", () => {
    const sorts = many.activities.filter((activity) => activity.kind === "sort_category");
    expect(sorts.length).toBeGreaterThan(0);
    for (const activity of sorts) {
      expect(activity.bins, activity.id).toHaveLength(2);
      const keys = activity.bins!.map((bin) => bin.key);
      expect(new Set(keys).size).toBe(2);
      expect(keys, activity.id).toContain(correctBinKey(activity));
    }
  });

  it("gives story_moment beats to tap through before it asks anything", () => {
    const stories = many.activities.filter((activity) => activity.kind === "story_moment");
    expect(stories.length).toBeGreaterThan(0);
    for (const activity of stories) {
      expect(activity.beats!.length, activity.id).toBeGreaterThan(0);
      for (const beat of activity.beats!) {
        expect(beat.text_ar.trim(), activity.id).not.toBe("");
      }
    }
  });

  it("does not ask a child to file a letter under a category", () => {
    // "Is أ a letter or a colour" is a question about the curriculum's filing
    // system, not about the alphabet.
    const letters = buildLocalSession({
      seed: 5,
      categories: ["letters"],
      activityCount: 12,
    });
    expect(
      letters.activities.filter((activity) => activity.kind === "sort_category"),
    ).toEqual([]);
  });
});

describe("world selection", () => {
  it("draws only from the chosen worlds", () => {
    for (const category of CATEGORY_ORDER) {
      const built = buildLocalSession({ seed: 2, categories: [category] });
      for (const activity of built.activities) {
        expect(skill(activity.skill_id)!.category, activity.id).toBe(category);
      }
    }
  });

  it("still fills a session from the smallest world", () => {
    // Colours is ten skills and a session is eight activities. A world that
    // cannot fill a session would end one early, which reads to a child as the
    // app giving up.
    const built = buildLocalSession({ seed: 4, categories: ["colors"] });
    expect(built.activities).toHaveLength(8);
  });
});
