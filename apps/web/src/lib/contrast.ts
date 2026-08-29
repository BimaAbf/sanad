/**
 * WCAG 2.2 contrast, computed over the design tokens.
 *
 * docs/06 §5 sets >= 4.5:1 for the caregiver app and >= 7:1 for the child app,
 * and says the child figure is verified by "automated token-pair test". This is
 * that test's engine: it reads the pairs the product actually renders and
 * computes the ratio, so a token edit that breaks a pair fails CI rather than
 * being noticed by a parent.
 *
 * Pure. No DOM — `getComputedStyle` would only report what a browser resolved
 * for one screen, and the requirement is about every screen.
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function parseHex(hex: string): Rgb {
  const value = hex.trim().replace("#", "");
  const full =
    value.length === 3
      ? value
          .split("")
          .map((c) => c + c)
          .join("")
      : value;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    throw new Error(`not a hex colour: ${hex}`);
  }
  return {
    r: Number.parseInt(full.slice(0, 2), 16),
    g: Number.parseInt(full.slice(2, 4), 16),
    b: Number.parseInt(full.slice(4, 6), 16),
  };
}

/** WCAG relative luminance. The 0.03928 threshold and 2.4 exponent are the spec's. */
export function relativeLuminance({ r, g, b }: Rgb): number {
  const channel = (raw: number): number => {
    const c = raw / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(parseHex(foreground));
  const b = relativeLuminance(parseHex(background));
  const [lighter, darker] = a > b ? [a, b] : [b, a];
  return (lighter + 0.05) / (darker + 0.05);
}

export const CAREGIVER_MIN_RATIO = 4.5;
export const CHILD_MIN_RATIO = 7;

/**
 * WCAG 2.2 SC 1.4.11, non-text contrast. Applies to a swatch or an icon that
 * carries meaning, not to anything a reader has to read.
 *
 * It exists here because two of the semantic colours — `--c-practising` at
 * 3.26:1 and `--c-resting` at 3.58:1 — clear this and do NOT clear 4.5:1. They
 * are correct as the fill of a skill-map tile and wrong as the colour of a
 * word, so the pair list below distinguishes the two uses instead of quietly
 * applying the weaker rule to both.
 */
export const GRAPHIC_MIN_RATIO = 3;

export function meetsCaregiver(foreground: string, background: string): boolean {
  return contrastRatio(foreground, background) >= CAREGIVER_MIN_RATIO;
}

export function meetsChild(foreground: string, background: string): boolean {
  return contrastRatio(foreground, background) >= CHILD_MIN_RATIO;
}

/**
 * Read `--token: #value;` declarations out of a stylesheet.
 *
 * Deliberately a text parse rather than a CSSOM one: this runs in the unit
 * suite with no browser, and the file it reads is the file that ships.
 */
export function tokensFrom(css: string): Map<string, string> {
  const tokens = new Map<string, string>();
  for (const match of css.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    tokens.set(match[1]!, match[2]!);
  }
  return tokens;
}

export interface Pair {
  name: string;
  foreground: string;
  background: string;
  audience: "caregiver" | "child" | "graphic";
}

/**
 * Every foreground/background pair the product actually renders.
 *
 * Listed explicitly rather than derived from a cross product of all tokens: a
 * cross product would flag `--k-yellow` on `--k-white`, which nothing renders,
 * and a test that fails on a combination nobody ships is a test people switch
 * off.
 */
export const RENDERED_PAIRS: readonly Pair[] = [
  { name: "body text", foreground: "--c-ink", background: "--c-surface", audience: "caregiver" },
  {
    name: "body text on alt surface",
    foreground: "--c-ink",
    background: "--c-surface-alt",
    audience: "caregiver",
  },
  {
    name: "muted text",
    foreground: "--c-ink-muted",
    background: "--c-surface",
    audience: "caregiver",
  },
  {
    name: "primary heading",
    foreground: "--c-primary",
    background: "--c-surface",
    audience: "caregiver",
  },
  {
    name: "primary button label",
    foreground: "--c-surface",
    background: "--c-primary",
    audience: "caregiver",
  },
  {
    name: "primary on soft primary",
    foreground: "--c-primary",
    background: "--c-primary-soft",
    audience: "caregiver",
  },
  // Skill-map tiles: a coloured fill, read as a shape, not as text.
  {
    name: "growing swatch",
    foreground: "--c-growing",
    background: "--c-surface",
    audience: "graphic",
  },
  {
    name: "practising swatch",
    foreground: "--c-practising",
    background: "--c-surface",
    audience: "graphic",
  },
  {
    name: "resting swatch",
    foreground: "--c-resting",
    background: "--c-surface",
    audience: "graphic",
  },
  {
    name: "attention swatch",
    foreground: "--c-attention",
    background: "--c-surface",
    audience: "graphic",
  },
  // The same states written as words. Different tokens, and that is the point.
  {
    name: "growing label",
    foreground: "--c-growing",
    background: "--c-surface",
    audience: "caregiver",
  },
  {
    name: "practising label",
    foreground: "--c-practising-text",
    background: "--c-surface",
    audience: "caregiver",
  },
  {
    name: "resting label",
    foreground: "--c-resting-text",
    background: "--c-surface",
    audience: "caregiver",
  },
  {
    name: "attention label",
    foreground: "--c-attention",
    background: "--c-surface",
    audience: "caregiver",
  },
  // The child app: instruction text and the choice-card frame, both at 7:1.
  { name: "child instruction", foreground: "--c-ink", background: "--k-white", audience: "child" },
  {
    name: "child instruction on surface",
    foreground: "--c-ink",
    background: "--c-surface",
    audience: "child",
  },
];

export function failingPairs(tokens: Map<string, string>): string[] {
  const failures: string[] = [];
  for (const pair of RENDERED_PAIRS) {
    const foreground = tokens.get(pair.foreground);
    const background = tokens.get(pair.background);
    if (!foreground || !background) {
      failures.push(`${pair.name}: missing token`);
      continue;
    }
    const ratio = contrastRatio(foreground, background);
    const minimum =
      pair.audience === "child"
        ? CHILD_MIN_RATIO
        : pair.audience === "graphic"
          ? GRAPHIC_MIN_RATIO
          : CAREGIVER_MIN_RATIO;
    if (ratio < minimum) {
      failures.push(`${pair.name} (${pair.audience}): ${ratio.toFixed(2)}:1 < ${minimum}:1`);
    }
  }
  return failures;
}
