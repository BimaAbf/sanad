import { ArtFrame, INK, K } from "@/components/art/frame";
import { KEYWORD_ART, OBJECT_ART } from "@/components/art/objects";
import { skill, type Skill } from "@/content/curriculum";

/**
 * The picture for one curriculum skill, whatever kind of thing it is.
 *
 * Four categories need four fundamentally different drawings and this is the
 * one place that decides which:
 *
 * * **Objects** (body parts, household, social) — a vector drawing, looked up
 *   by skill code in `OBJECT_ART`.
 * * **Colours** — a filled disc, and nothing else in the frame. Anything else
 *   in the picture is a second thing to name, and this activity is asking the
 *   child to name exactly one.
 * * **Numbers** — the Eastern Arabic glyph *and* that many counting dots.
 *   docs/02 teaches quantity and numeral together; a bare `٧` is a shape, and a
 *   child who can only match shapes would score as knowing seven.
 * * **Letters** — the glyph on a tile, identical in construction for all 28.
 *   Keyword pictures (أ → أسد) exist but appear only in the story moment, so
 *   that no letter card looks richer than another.
 *
 * Glyphs are HTML text, not SVG `<text>`: the app's real Arabic font applies,
 * they reflow at 200 % zoom (docs/06 §5), and a screen reader can reach them.
 */

/** Rotated across the 28 letters so the alphabet is not one flat colour. */
const TILE_TINTS = ["#E4F2EE", "#FDF0E4", "#EDE9F7", "#E6F0FA"] as const;

function tintFor(item: Skill): string {
  return TILE_TINTS[item.introOrder % TILE_TINTS.length]!;
}

function ColourDisc({ hex }: { hex: string }) {
  return (
    <ArtFrame>
      <circle cx="60" cy="60" r="46" fill={hex} stroke={INK} strokeWidth="4" />
      {/* One highlight, so a flat disc still reads as a physical object. It is
          white at low opacity rather than a lighter tint of the colour, so it
          never becomes a second, nameable colour on the card. */}
      <ellipse cx="44" cy="42" rx="15" ry="10" fill={K.white} opacity="0.35" />
    </ArtFrame>
  );
}

/** Counting dots, laid out in rows of five — the way a hand counts. */
function CountingDots({ count }: { count: number }) {
  const rows = count > 5 ? [5, count - 5] : [count];
  return (
    <span
      aria-hidden
      className="flex flex-col items-center gap-1"
      style={{ marginBlockStart: "4px" }}
    >
      {rows.map((row, rowIndex) => (
        <span key={rowIndex} className="flex gap-1">
          {Array.from({ length: row }, (_, index) => (
            <span
              key={index}
              className="block rounded-pill"
              style={{
                inlineSize: "10px",
                blockSize: "10px",
                backgroundColor: rowIndex === 0 ? K.orange : K.blue,
              }}
            />
          ))}
        </span>
      ))}
    </span>
  );
}

function GlyphTile({ item, glyphSize }: { item: Skill; glyphSize: string }) {
  return (
    <span
      aria-hidden
      className="grid h-full w-full place-items-center rounded-lg"
      style={{ backgroundColor: tintFor(item) }}
    >
      <span className="flex flex-col items-center">
        <span
          className="font-semibold leading-tight"
          style={{ fontSize: glyphSize, color: INK }}
        >
          {item.labelAr}
        </span>
        {item.count ? <CountingDots count={item.count} /> : null}
      </span>
    </span>
  );
}

/**
 * `imageUrl` wins when the manifest supplies one.
 *
 * That is the wire-up seam for real illustrations: C05 starts sending
 * `choices[].image` and these drawings become the offline fallback without a
 * component changing. A plain `<img>` on purpose — the manifest's URLs are
 * already in the Cache API, and routing them through next/image would re-fetch
 * at render time and break the offline guarantee.
 */
export function SkillArt({
  code,
  imageUrl,
  size = 120,
}: {
  code: string;
  imageUrl?: string | undefined;
  size?: number;
}) {
  const item = skill(code);
  const box = { inlineSize: `${size}px`, blockSize: `${size}px` } as const;

  if (imageUrl) {
    return (
      <img src={imageUrl} alt="" aria-hidden style={box} className="object-contain" />
    );
  }

  if (!item) {
    return <span aria-hidden style={box} className="block rounded-lg bg-surface-alt" />;
  }

  if (item.category === "colors" && item.hex) {
    return (
      <span style={box} className="block">
        <ColourDisc hex={item.hex} />
      </span>
    );
  }

  if (item.category === "numbers" || item.category === "letters") {
    return (
      <span style={box} className="block">
        <GlyphTile item={item} glyphSize={`${Math.round(size * 0.46)}px`} />
      </span>
    );
  }

  const Drawing = OBJECT_ART[item.code];
  if (!Drawing) {
    // No drawing yet. A legible label tile beats a broken-image icon, and this
    // is what any newly seeded skill looks like on the day it is added.
    return (
      <span style={box} className="block">
        <GlyphTile item={item} glyphSize={`${Math.round(size * 0.18)}px`} />
      </span>
    );
  }

  return (
    <span style={box} className="block">
      <ArtFrame>
        <Drawing />
      </ArtFrame>
    </span>
  );
}

/** The keyword picture for a letter, when one has been drawn. */
export function LetterKeywordArt({ code, size = 120 }: { code: string; size?: number }) {
  const Drawing = KEYWORD_ART[code];
  if (!Drawing) return null;
  return (
    <span style={{ inlineSize: `${size}px`, blockSize: `${size}px` }} className="block">
      <ArtFrame>
        <Drawing />
      </ArtFrame>
    </span>
  );
}

export function hasKeywordArt(code: string): boolean {
  return code in KEYWORD_ART;
}
