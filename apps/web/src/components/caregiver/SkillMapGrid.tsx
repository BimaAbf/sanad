import { SkillArt } from "@/components/art/SkillArt";
import { arabicFraction } from "@/lib/numerals";

/**
 * The 88-skill map.
 *
 * Three rules from docs/06 §2, §3 and §5 that this component exists to enforce:
 *
 * * The state is conveyed by a **swatch plus a word**, never by colour alone.
 *   Colour alone fails WCAG 1.4.1 and, more to the point, fails a parent who is
 *   colour-blind and is being told something about their child.
 * * The word uses `--c-*-text` tokens, not the swatch tokens. `--c-practising`
 *   is 3.26:1 on white — fine as a tile, unreadable as a label. See
 *   `lib/contrast.ts`.
 * * The count is a **fraction, never a percentage**. docs/06 §3 bans "score",
 *   and a percentage is a score with the word taken off.
 *
 * The picture on each tile is the same drawing the child taps in `/play`,
 * looked up by the same skill code. That is the point of it: a parent scanning
 * this list is looking for the thing they watched their child do, and "فرشة
 * سنان" in a list of twenty words is much harder to find than the toothbrush.
 */
export type MasteryState =
  | "not_started"
  | "emerging"
  | "practising"
  | "mastered"
  | "retained";

const SWATCH: Record<MasteryState, string> = {
  not_started: "var(--c-border)",
  emerging: "var(--c-practising)",
  practising: "var(--c-practising)",
  mastered: "var(--c-growing)",
  retained: "var(--c-growing)",
};

const TEXT: Record<MasteryState, string> = {
  not_started: "var(--c-resting-text)",
  emerging: "var(--c-practising-text)",
  practising: "var(--c-practising-text)",
  mastered: "var(--c-growing)",
  retained: "var(--c-growing)",
};

/** A skill the child has reached at all. Drives the per-category count. */
const STARTED: ReadonlySet<MasteryState> = new Set<MasteryState>([
  "emerging",
  "practising",
  "mastered",
  "retained",
]);

export interface SkillCell {
  skillId: string;
  code: string;
  labelAr: string;
  state: MasteryState;
}

export function SkillMapGrid({
  category,
  categoryLabel,
  skills,
  stateLabels,
}: {
  category: string;
  categoryLabel: string;
  skills: SkillCell[];
  stateLabels: Record<MasteryState, string>;
}) {
  const started = skills.filter((skill) => STARTED.has(skill.state)).length;

  return (
    <section data-testid={`skill-group-${category}`} className="mb-8">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">{categoryLabel}</h2>
        {/* Not a heading and not a progress bar. A parent glancing down the
            page wants to know where there is something to look at; a bar would
            invite them to compare the six bars against each other. */}
        <p data-testid={`skill-count-${category}`} className="text-sm text-ink-muted">
          {arabicFraction(started, skills.length)}
        </p>
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {skills.map((skill) => (
          <li
            key={skill.skillId}
            data-testid={`skill-${skill.code}`}
            data-state={skill.state}
            className="flex items-center gap-3 rounded-md border border-border bg-surface p-3"
          >
            {/* The drawing is decoration here: the label beside it is the same
                word, so a screen reader announcing both would say it twice. */}
            <SkillArt code={skill.code} size={40} />
            <span className="min-w-0">
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="block shrink-0 rounded-sm"
                  style={{
                    inlineSize: "14px",
                    blockSize: "14px",
                    backgroundColor: SWATCH[skill.state],
                  }}
                />
                <span className="break-words font-semibold text-ink">
                  {skill.labelAr}
                </span>
              </span>
              <span className="mt-1 block text-sm" style={{ color: TEXT[skill.state] }}>
                {stateLabels[skill.state]}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
