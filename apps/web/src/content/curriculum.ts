/**
 * The 88-skill curriculum, client-side.
 *
 * ============================================================================
 * REVIEWED-BY:
 * ============================================================================
 * ^^ EMPTY. Every Arabic string below that is not a bare glyph is written by an
 * agent and has NOT been reviewed by a native Egyptian Arabic speaker. The
 * `code` and `labelAr` values are transcribed from
 * `services/api/seeds/curriculum.py` (itself transcribed from docs/02 §10.1);
 * `altAr` and the 25 unmarked letter keywords are new here and are
 * PLACEHOLDER. → REVIEW-QUEUE.md
 * ============================================================================
 *
 * ## Why this file exists at all
 *
 * The curriculum is owned by the API (C05 Content Service) and arrives in a
 * session manifest. This is not a second source of truth for it — it is the
 * *presentation* half the manifest does not and should not carry: which shape
 * to draw for `hh_spoon`, which hex fills `color_red`, how many counting dots
 * sit under `num_7`.
 *
 * `code` is the join key. When the API is wired up a manifest activity names
 * `skill_id: "color_red"` and the art registry finds the drawing by that code.
 * No artwork ships in the manifest and none needs to — that is what keeps a
 * session under the 4 MB budget in docs/06 §6.
 *
 * Codes and order match the seed exactly, so `introOrder` here is the same
 * `intro_order` the adaptive engine schedules against.
 */

export const REVIEWED_BY = "";

export type SkillCategory =
  | "colors"
  | "body_parts"
  | "social"
  | "household"
  | "numbers"
  | "letters";

/** The six categories in introduction order — most concrete first. */
export const CATEGORY_ORDER: readonly SkillCategory[] = [
  "colors",
  "body_parts",
  "social",
  "household",
  "numbers",
  "letters",
];

export interface Skill {
  /** Join key with the API. Never change one without changing the seed. */
  code: string;
  category: SkillCategory;
  /** What is written on screen. For letters and numbers this is the glyph. */
  labelAr: string;
  /** What Nour says. Egyptian colloquial; differs from labelAr for glyphs. */
  labelEgy: string;
  /** Image alt text. Mandatory — docs/06 §5 makes it a DB column for a reason. */
  altAr: string;
  /** 1–5, from the seed's `_tier_for`. Drives distractor contrast. */
  tier: number;
  introOrder: number;
  /** Colours only: the fill actually drawn, from the `--k-*` child palette. */
  hex?: string;
  /** Numbers only: how many counting dots to draw. */
  count?: number;
  /** Letters only: the keyword whose initial sound the letter makes. */
  keywordAr?: string;
}

/* -------------------------------------------------------------------------- */
/* Colours — 10. The hex values are the `--k-*` tokens from docs/06 §2, which   */
/* are the ones a child is taught to name. A "red" card filled with anything    */
/* other than --k-red teaches the wrong word for the wrong colour.              */
/* -------------------------------------------------------------------------- */

const COLOURS: Array<[suffix: string, label: string, hex: string, alt: string]> = [
  ["red", "أحمر", "#D93A2B", "دايرة حمرا"],
  ["blue", "أزرق", "#1C6BBF", "دايرة زرقا"],
  ["yellow", "أصفر", "#F0B429", "دايرة صفرا"],
  ["green", "أخضر", "#2E8B4A", "دايرة خضرا"],
  ["white", "أبيض", "#FFFFFF", "دايرة بيضا"],
  ["black", "أسود", "#2B2B2B", "دايرة سودا"],
  ["orange", "برتقالي", "#E87722", "دايرة برتقاني"],
  ["brown", "بني", "#8B5E3C", "دايرة بنّي"],
  ["pink", "وردي", "#D9538C", "دايرة وردي"],
  ["purple", "بنفسجي", "#7B4FA8", "دايرة بنفسجي"],
];

/* -------------------------------------------------------------------------- */
/* Body parts — 10                                                             */
/* -------------------------------------------------------------------------- */

const BODY_PARTS: Array<[suffix: string, label: string, alt: string]> = [
  ["head", "راس", "راس طفل"],
  ["hair", "شعر", "شعر"],
  ["eye", "عين", "عين"],
  ["ear", "ودن", "ودن"],
  ["nose", "مناخير", "مناخير"],
  ["mouth", "بق", "بق بيبتسم"],
  ["teeth", "سنان", "سنان"],
  ["hand", "إيد", "إيد مفتوحة"],
  ["leg", "رجل", "رجل"],
  ["tummy", "بطن", "بطن"],
];

/* -------------------------------------------------------------------------- */
/* Social phrases — 10. Drawn as a moment, not as an object: "صباح الخير" is a  */
/* sun over a house, because there is no picture of a greeting.                 */
/* -------------------------------------------------------------------------- */

const SOCIAL: Array<[suffix: string, label: string, alt: string]> = [
  ["good_morning", "صباح الخير", "شمس طالعة الصبح"],
  ["goodbye", "مع السلامة", "إيد بتسلّم"],
  ["thanks", "شكرا", "قلب في الإيد"],
  ["please", "من فضلك", "إيد مفتوحة بتطلب"],
  ["yes", "أيوه", "علامة صح"],
  ["no", "لأ", "إيد بتقول لأ"],
  ["come", "تعالى", "إيد بتنادي"],
  ["dad", "بابا", "وش بابا"],
  ["mum", "ماما", "وش ماما"],
  ["my_name", "اسمي", "طفل بيشاور على نفسه"],
];

/* -------------------------------------------------------------------------- */
/* Household objects — 20                                                      */
/* -------------------------------------------------------------------------- */

const HOUSEHOLD: Array<[suffix: string, label: string, alt: string]> = [
  ["toothbrush", "فرشة سنان", "فرشة سنان"],
  ["toothpaste", "معجون", "أنبوبة معجون"],
  ["soap", "صابونة", "صابونة"],
  ["towel", "فوطة", "فوطة متعلقة"],
  ["fork", "شوكة", "شوكة"],
  ["spoon", "معلقة", "معلقة"],
  ["knife", "سكينة", "سكينة"],
  ["plate", "طبق", "طبق"],
  ["cup", "كوباية", "كوباية"],
  ["water_glass", "كوباية مية", "كوباية فيها مية"],
  ["chair", "كرسي", "كرسي"],
  ["table", "ترابيزة", "ترابيزة"],
  ["bed", "سرير", "سرير"],
  ["pillow", "مخدة", "مخدة"],
  ["door", "باب", "باب"],
  ["window", "شباك", "شباك"],
  ["shoes", "جزمة", "جزمة"],
  ["bag", "شنطة", "شنطة"],
  ["clothes", "لبس", "تي شيرت"],
  ["comb", "مشط", "مشط"],
];

/* -------------------------------------------------------------------------- */
/* Numbers 1–10. `labelAr` is the Eastern Arabic glyph — docs/06 §1 requires    */
/* Eastern Arabic numerals for everything a child sees.                        */
/* -------------------------------------------------------------------------- */

const NUMERALS: Array<[value: number, glyph: string, word: string]> = [
  [1, "١", "واحد"],
  [2, "٢", "اتنين"],
  [3, "٣", "تلاتة"],
  [4, "٤", "أربعة"],
  [5, "٥", "خمسة"],
  [6, "٦", "ستة"],
  [7, "٧", "سبعة"],
  [8, "٨", "تمانية"],
  [9, "٩", "تسعة"],
  [10, "١٠", "عشرة"],
];

/* -------------------------------------------------------------------------- */
/* Letters — the 28 of the Arabic alphabet.                                    */
/*                                                                             */
/* `nameAr` is what the letter is CALLED, and is what Nour says. `keywordAr`  */
/* is the word whose initial sound it makes. docs/02 §10.1                     */
/* gives three (أ → أسد, ب → بطة, ت → تفاحة) and those are transcribed. The     */
/* other 25 are PLACEHOLDER: chosen for concreteness and for being words a      */
/* child in Egypt already hears at home, but a phonics decision belongs to a    */
/* speech therapist, not to the agent that wrote this list.                     */
/* -------------------------------------------------------------------------- */

const LETTERS: Array<[name: string, glyph: string, nameAr: string, keyword: string]> = [
  ["alef", "أ", "ألف", "أسد"],
  ["baa", "ب", "با", "بطة"],
  ["taa", "ت", "تا", "تفاحة"],
  ["thaa", "ث", "ثا", "ثعلب"],
  ["jeem", "ج", "جيم", "جمل"],
  ["haa", "ح", "حا", "حصان"],
  ["khaa", "خ", "خا", "خروف"],
  ["dal", "د", "دال", "ديك"],
  ["thal", "ذ", "ذال", "ذرة"],
  ["raa", "ر", "را", "رمانة"],
  ["zay", "ز", "زاي", "زرافة"],
  ["seen", "س", "سين", "سمكة"],
  ["sheen", "ش", "شين", "شمس"],
  ["sad", "ص", "صاد", "صاروخ"],
  ["dad", "ض", "ضاد", "ضفدع"],
  ["tah", "ط", "طا", "طيارة"],
  ["zah", "ظ", "ظا", "ظرف"],
  ["ain", "ع", "عين", "عصفورة"],
  ["ghain", "غ", "غين", "غزالة"],
  ["faa", "ف", "فا", "فيل"],
  ["qaf", "ق", "قاف", "قمر"],
  ["kaf", "ك", "كاف", "كتاب"],
  ["lam", "ل", "لام", "ليمونة"],
  ["meem", "م", "ميم", "موزة"],
  ["noon", "ن", "نون", "نحلة"],
  ["haa2", "ه", "ها", "هدية"],
  ["waw", "و", "واو", "وردة"],
  ["yaa", "ي", "يا", "يد"],
];

/** The three keywords docs/02 §10.1 actually supplies. The rest need review. */
export const REVIEWED_LETTER_KEYWORDS: readonly string[] = ["alef", "baa", "taa"];

/** Mirrors `_tier_for` in services/api/seeds/curriculum.py. */
function tierFor(category: SkillCategory, index: number): number {
  if (category === "colors" || category === "body_parts") return index < 5 ? 1 : 2;
  if (category === "household") return index < 10 ? 2 : 3;
  if (category === "social") return index < 4 ? 1 : 2;
  if (category === "numbers") return index < 5 ? 2 : 3;
  return index < 14 ? 3 : 4; // letters
}

function build(): Skill[] {
  const skills: Skill[] = [];
  let order = 0;

  const add = (item: Omit<Skill, "introOrder">) => {
    skills.push({ ...item, introOrder: order });
    order += 1;
  };

  COLOURS.forEach(([suffix, label, hex, alt], index) =>
    add({
      code: `color_${suffix}`,
      category: "colors",
      labelAr: label,
      labelEgy: label,
      altAr: alt,
      tier: tierFor("colors", index),
      hex,
    }),
  );

  BODY_PARTS.forEach(([suffix, label, alt], index) =>
    add({
      code: `body_${suffix}`,
      category: "body_parts",
      labelAr: label,
      labelEgy: label,
      altAr: alt,
      tier: tierFor("body_parts", index),
    }),
  );

  SOCIAL.forEach(([suffix, label, alt], index) =>
    add({
      code: `social_${suffix}`,
      category: "social",
      labelAr: label,
      labelEgy: label,
      altAr: alt,
      tier: tierFor("social", index),
    }),
  );

  HOUSEHOLD.forEach(([suffix, label, alt], index) =>
    add({
      code: `hh_${suffix}`,
      category: "household",
      labelAr: label,
      labelEgy: label,
      altAr: alt,
      tier: tierFor("household", index),
    }),
  );

  NUMERALS.forEach(([value, glyph, word], index) =>
    add({
      code: `num_${value}`,
      category: "numbers",
      labelAr: glyph,
      labelEgy: word,
      altAr: `${word} — ${glyph}`,
      tier: tierFor("numbers", index),
      count: value,
    }),
  );

  LETTERS.forEach(([name, glyph, nameAr, keyword], index) =>
    add({
      code: `letter_${name}`,
      category: "letters",
      labelAr: glyph,
      // The letter's NAME, not its keyword.
      //
      // `label_egy` in the API seed is the keyword — `أ` carries `أسد` — and
      // taking that literally produced an instruction reading "وريني زرافة"
      // ("show me a giraffe") beside a card showing `ز` and a card showing `٥`.
      // There was no giraffe on the screen. What Nour says has to name the
      // thing the child is looking at, so a letter is spoken as a letter, and
      // the keyword appears only in the story moment, where it is introduced
      // as one ("أ زي أسد"). The seed has the same latent bug for TTS.
      // → REVIEW-QUEUE.md #14
      labelEgy: nameAr,
      altAr: `حرف ${glyph}`,
      tier: tierFor("letters", index),
      keywordAr: keyword,
    }),
  );

  return skills;
}

export const SKILLS: readonly Skill[] = build();

const BY_CODE = new Map(SKILLS.map((item) => [item.code, item]));

export function skill(code: string): Skill | undefined {
  return BY_CODE.get(code);
}

export function skillsIn(category: SkillCategory): Skill[] {
  return SKILLS.filter((item) => item.category === category);
}

/**
 * The label a child hears, which is not always the label they see.
 *
 * `٣` is written but "تلاتة" is said, and an instruction reading "وريني ٣"
 * would be a sentence no adult says out loud to a child.
 */
export function spokenLabel(item: Skill): string {
  return item.labelEgy;
}
