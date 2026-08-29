/**
 * The session manifest — the document the child app runs a whole session from.
 *
 * ## The contract
 *
 * `SessionManifest` is transcribed from the JSON in docs/04c §C05, field for
 * field, including the snake_case. It is what `POST /play/sessions` will
 * return. Four fields are additions this file introduces and the API does not
 * emit yet — `pairs`, `bins`, `beats`, and `card` — because docs/01 §1 names
 * five `activity_kind` values in the enum (`listen_point`, `match_pair`,
 * `say_it`, `sort_category`, `story_moment`) and the documented manifest only
 * carries enough data to render the first of them. They are marked and grouped
 * below rather than smuggled in. → REVIEW-QUEUE.md
 *
 * ## The local builder
 *
 * `buildLocalSession` produces a valid manifest from the bundled curriculum, so
 * the child app is playable end to end today, with no API and no network. It is
 * NOT a mock in the test-double sense — it implements the same errorless
 * distractor rule the real service does (docs/04c §C05) and produces the same
 * shape, so the swap is one function call in `loadSession`.
 *
 * Everything here is pure and deterministic given a seed. Two reasons that
 * matters more than usual: a random session cannot be reproduced when a parent
 * reports that something went wrong, and `Math.random` in a component that
 * renders on both sides of a hydration boundary is a class of bug this app
 * cannot afford.
 */

import {
  CATEGORY_ORDER,
  SKILLS,
  skill,
  spokenLabel,
  type Skill,
  type SkillCategory,
} from "@/content/curriculum";
import { clampChoices, MAX_CHOICES } from "@/lib/interaction";

/** docs/01 §1 — the `activity_kind` enum, in full. */
export type ActivityKind =
  | "listen_point"
  | "match_pair"
  | "say_it"
  | "sort_category"
  | "story_moment";

/** docs/04c — `modality`. Never two expressive activities in a row. */
export type Modality = "receptive" | "expressive";

export const MODALITY_OF: Record<ActivityKind, Modality> = {
  listen_point: "receptive",
  match_pair: "receptive",
  sort_category: "receptive",
  say_it: "expressive",
  story_moment: "receptive",
};

export interface ManifestChoice {
  skill_id: string;
  /** Absolute CDN URL when the API supplies one; the bundled art draws it if not. */
  image?: string;
  alt_ar: string;
  label_ar: string;
  correct: boolean;
}

export interface PromptRung {
  level: "gestural" | "partial_verbal" | "full_model";
  audio?: string;
  highlight?: "correct";
  auto_select?: boolean;
}

/** ADDITION — `sort_category`. Two bins; every card belongs in exactly one. */
export interface ManifestBin {
  key: string;
  label_ar: string;
  /** A skill code whose drawing illustrates the bin. */
  art_skill_id: string;
}

/** ADDITION — `story_moment`. Beats are tapped through, never timed. */
export interface ManifestBeat {
  text_ar: string;
  audio?: string;
  /** A skill code to illustrate this beat, if any. */
  art_skill_id?: string;
  /** Letters only: show the keyword picture rather than the glyph. */
  show_keyword?: boolean;
}

export interface ManifestActivity {
  id: string;
  kind: ActivityKind;
  skill_id: string;
  /** ≤ 5 words after substitution. docs/06 §4. */
  instruction_ar: string;
  instruction_audio?: string;
  /** What Nour says out loud — the word, not the glyph. */
  spoken_ar: string;
  choices: ManifestChoice[];
  prompt_ladder: PromptRung[];
  /** ADDITION — `match_pair`: the card the child is matching against. */
  card?: ManifestChoice;
  /** ADDITION — `sort_category`: exactly two. */
  bins?: ManifestBin[];
  /** ADDITION — `story_moment`: 2–3 beats. */
  beats?: ManifestBeat[];
}

export interface SessionManifest {
  session_id: string;
  child: {
    wait_time_ms: number;
    max_choices: number;
    audio_rate_pct: number;
    calm_mode: boolean;
  };
  activities: ManifestActivity[];
  closing_audio?: string;
  expires_at?: string;
  /** True when this manifest came from the bundled curriculum, not the API. */
  local: boolean;
}

/* ------------------------------ the builder ------------------------------ */

/**
 * A small deterministic PRNG (mulberry32). Not for anything security-adjacent —
 * it exists so "session 7 for this child" is the same session every time it is
 * rebuilt, which is what makes a bug report reproducible.
 */
function rng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle<T>(items: T[], random: () => number): T[] {
  const out = [...items];
  for (let index = out.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1));
    [out[index], out[swap]] = [out[swap]!, out[index]!];
  }
  return out;
}

/**
 * The errorless-learning rule from docs/04c §C05, as much of it as a client can
 * apply.
 *
 * At tier ≤ 2 a distractor must come from a *different category* — a red card
 * never sits beside an orange one, a فرشة سنان never beside a مشط. The full
 * server-side rule also uses perceptual colour distance, first phoneme and a
 * recent-distractor memory; none of those data are in the bundle, so this is
 * the coarse half of the rule, and it is the half that prevents the failure
 * mode that matters: turning a comprehension task into a discrimination task.
 */
export function chooseDistractors(
  target: Skill,
  count: number,
  random: () => number,
  exclude: ReadonlySet<string> = new Set(),
): Skill[] {
  const differentCategory = SKILLS.filter(
    (item) =>
      item.code !== target.code &&
      !exclude.has(item.code) &&
      item.category !== target.category,
  );
  const sameCategory = SKILLS.filter(
    (item) =>
      item.code !== target.code &&
      !exclude.has(item.code) &&
      item.category === target.category,
  );

  // Tier 3+ may use near-misses; tier 1–2 never may. When the cross-category
  // pool somehow runs dry the same-category pool is the fallback, because a
  // session that renders one choice is worse than one with a closer distractor.
  const pool =
    target.tier <= 2
      ? [...shuffle(differentCategory, random), ...shuffle(sameCategory, random)]
      : [...shuffle(sameCategory, random), ...shuffle(differentCategory, random)];

  return pool.slice(0, count);
}

function toChoice(item: Skill, correct: boolean): ManifestChoice {
  return {
    skill_id: item.code,
    alt_ar: item.altAr,
    label_ar: item.labelAr,
    correct,
  };
}

/**
 * The prompt ladder, identical for every activity.
 *
 * docs/06 §4 fixes the three rungs and what each one does on screen. There is
 * no per-activity variation because a ladder a child has to re-learn per
 * activity is not a ladder.
 */
const LADDER: PromptRung[] = [
  { level: "gestural", highlight: "correct" },
  { level: "partial_verbal", highlight: "correct" },
  { level: "full_model", highlight: "correct", auto_select: true },
];

/** Instructions, ≤ 5 words after the label is substituted. docs/06 §4. */
function instructionFor(kind: ActivityKind, item: Skill): string {
  const label = spokenLabel(item);
  switch (kind) {
    case "listen_point":
      return `وريني ${label}`;
    case "match_pair":
      return "لاقي زيها";
    case "say_it":
      return `قول ${label}`;
    case "sort_category":
      return "حطها في مكانها";
    case "story_moment":
      return `دي ${label}`;
  }
}

const CATEGORY_LABEL: Record<SkillCategory, string> = {
  colors: "ألوان",
  body_parts: "جسمي",
  social: "كلام",
  household: "البيت",
  numbers: "أرقام",
  letters: "حروف",
};

function buildListenPoint(
  item: Skill,
  choiceCount: number,
  random: () => number,
  id: string,
): ManifestActivity {
  const distractors = chooseDistractors(item, choiceCount - 1, random);
  return {
    id,
    kind: "listen_point",
    skill_id: item.code,
    instruction_ar: instructionFor("listen_point", item),
    spoken_ar: spokenLabel(item),
    choices: shuffle(
      [toChoice(item, true), ...distractors.map((d) => toChoice(d, false))],
      random,
    ),
    prompt_ladder: LADDER,
  };
}

function buildMatchPair(
  item: Skill,
  choiceCount: number,
  random: () => number,
  id: string,
): ManifestActivity {
  const distractors = chooseDistractors(item, choiceCount - 1, random);
  return {
    id,
    kind: "match_pair",
    skill_id: item.code,
    instruction_ar: instructionFor("match_pair", item),
    spoken_ar: spokenLabel(item),
    card: toChoice(item, true),
    choices: shuffle(
      [toChoice(item, true), ...distractors.map((d) => toChoice(d, false))],
      random,
    ),
    prompt_ladder: LADDER,
  };
}

function buildSayIt(item: Skill, id: string): ManifestActivity {
  return {
    id,
    kind: "say_it",
    skill_id: item.code,
    instruction_ar: instructionFor("say_it", item),
    spoken_ar: spokenLabel(item),
    // One choice, and it is the answer. There is nothing to get wrong here:
    // the child says the word, and either the recogniser or the caregiver
    // confirms it. The card exists so the child can see what they are naming.
    choices: [toChoice(item, true)],
    prompt_ladder: LADDER,
  };
}

function buildSortCategory(
  item: Skill,
  random: () => number,
  id: string,
): ManifestActivity {
  const otherCategory = shuffle(
    CATEGORY_ORDER.filter((category) => category !== item.category),
    random,
  )[0]!;
  const otherExample = shuffle(
    SKILLS.filter((candidate) => candidate.category === otherCategory),
    random,
  )[0]!;

  const bins: ManifestBin[] = shuffle(
    [
      {
        key: item.category,
        label_ar: CATEGORY_LABEL[item.category],
        art_skill_id: SKILLS.find(
          (candidate) => candidate.category === item.category && candidate.code !== item.code,
        )!.code,
      },
      {
        key: otherCategory,
        label_ar: CATEGORY_LABEL[otherCategory],
        art_skill_id: otherExample.code,
      },
    ],
    random,
  );

  return {
    id,
    kind: "sort_category",
    skill_id: item.code,
    instruction_ar: instructionFor("sort_category", item),
    spoken_ar: spokenLabel(item),
    choices: [toChoice(item, true)],
    bins,
    prompt_ladder: LADDER,
  };
}

function buildStoryMoment(
  item: Skill,
  choiceCount: number,
  random: () => number,
  id: string,
): ManifestActivity {
  const label = spokenLabel(item);
  const beats: ManifestBeat[] = [
    { text_ar: `شوف… ${label}`, art_skill_id: item.code },
    ...(item.keywordAr
      ? [{ text_ar: `${item.labelAr} زي ${item.keywordAr}`, art_skill_id: item.code, show_keyword: true }]
      : [{ text_ar: `${label}… ${label}`, art_skill_id: item.code }]),
  ];
  const distractors = chooseDistractors(item, choiceCount - 1, random);
  return {
    id,
    kind: "story_moment",
    skill_id: item.code,
    instruction_ar: instructionFor("story_moment", item),
    spoken_ar: label,
    beats,
    choices: shuffle(
      [toChoice(item, true), ...distractors.map((d) => toChoice(d, false))],
      random,
    ),
    prompt_ladder: LADDER,
  };
}

export interface LocalSessionOptions {
  /** Which worlds the session draws from. Empty means all of them. */
  categories?: readonly SkillCategory[];
  /** docs/04e — a session is short. 6–10 activities, 8 by default. */
  activityCount?: number;
  maxChoices?: number;
  waitTimeMs?: number;
  audioRatePct?: number;
  calmMode?: boolean;
  /** Same seed, same session. */
  seed?: number;
}

/**
 * Which kinds a skill can actually be taught with.
 *
 * `sort_category` needs a category the child can name, so it is not offered for
 * letters — "is أ a letter or a colour" is a question about the curriculum's
 * filing system, not about the alphabet. `story_moment` leads with the keyword,
 * so it is offered where there is one to lead with.
 */
function kindsFor(item: Skill): ActivityKind[] {
  const kinds: ActivityKind[] = ["listen_point", "match_pair", "say_it"];
  if (item.category !== "letters") kinds.push("sort_category");
  if (item.category === "letters" || item.category === "numbers") {
    kinds.push("story_moment");
  }
  return kinds;
}

export function buildLocalSession(options: LocalSessionOptions = {}): SessionManifest {
  const {
    categories = CATEGORY_ORDER,
    activityCount = 8,
    maxChoices = 2,
    waitTimeMs = 8000,
    audioRatePct = 85,
    calmMode = false,
    seed = 1,
  } = options;

  const random = rng(seed);
  const choiceCount = clampChoices(Math.min(maxChoices, MAX_CHOICES));

  const pool = categories.length
    ? SKILLS.filter((item) => categories.includes(item.category))
    : [...SKILLS];

  // Introduction order first, then a shuffle within it — the earliest skills of
  // each chosen world lead, which is what errorless learning wants, but two
  // consecutive sessions are not the same eight cards in the same order.
  const ordered = shuffle(
    [...pool].sort((a, b) => a.introOrder - b.introOrder).slice(0, Math.max(activityCount * 3, 12)),
    random,
  );

  const activities: ManifestActivity[] = [];
  let previousModality: Modality | null = null;

  for (let index = 0; activities.length < activityCount && index < ordered.length; index += 1) {
    const item = ordered[index]!;
    let kinds = kindsFor(item);

    // docs/04c §C07: "never two expressive tasks in a row." An expressive task
    // is the most effortful thing in the session; two back to back is how a
    // child decides they are done.
    if (previousModality === "expressive") {
      kinds = kinds.filter((kind) => MODALITY_OF[kind] === "receptive");
    }
    // The first activity is always receptive. Opening on "say the word" asks
    // for the hardest thing before the child has had a single success.
    if (activities.length === 0) {
      kinds = kinds.filter((kind) => MODALITY_OF[kind] === "receptive");
    }

    const kind = shuffle(kinds, random)[0]!;
    const id = `local-${index + 1}-${item.code}`;

    switch (kind) {
      case "listen_point":
        activities.push(buildListenPoint(item, choiceCount, random, id));
        break;
      case "match_pair":
        activities.push(buildMatchPair(item, choiceCount, random, id));
        break;
      case "say_it":
        activities.push(buildSayIt(item, id));
        break;
      case "sort_category":
        activities.push(buildSortCategory(item, random, id));
        break;
      case "story_moment":
        activities.push(buildStoryMoment(item, choiceCount, random, id));
        break;
    }
    previousModality = MODALITY_OF[kind];
  }

  return {
    session_id: `local-${seed}`,
    child: {
      wait_time_ms: waitTimeMs,
      max_choices: choiceCount,
      audio_rate_pct: audioRatePct,
      calm_mode: calmMode,
    },
    activities,
    local: true,
  };
}

/** The correct choice of an activity. Every activity has exactly one. */
export function correctChoice(activity: ManifestActivity): ManifestChoice | undefined {
  return activity.choices.find((choice) => choice.correct);
}

/** The bin a `sort_category` card belongs in. */
export function correctBinKey(activity: ManifestActivity): string | undefined {
  return skill(activity.skill_id)?.category;
}
