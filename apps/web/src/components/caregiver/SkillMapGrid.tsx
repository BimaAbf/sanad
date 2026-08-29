/**
 * The 88-skill map.
 *
 * Two rules from docs/06 §2 and §5 that this component exists to enforce:
 *
 * * The state is conveyed by a **swatch plus a word**, never by colour alone.
 *   Colour alone fails WCAG 1.4.1 and, more to the point, fails a parent who is
 *   colour-blind and is being told something about their child.
 * * The word uses `--c-*-text` tokens, not the swatch tokens. `--c-practising`
 *   is 3.26:1 on white — fine as a tile, unreadable as a label. See
 *   `lib/contrast.ts`.
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
  return (
    <section data-testid={`skill-group-${category}`} className="mb-8">
      <h2 className="mb-3 text-lg font-semibold text-ink">{categoryLabel}</h2>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {skills.map((skill) => (
          <li
            key={skill.skillId}
            data-testid={`skill-${skill.code}`}
            data-state={skill.state}
            className="rounded-md border border-border bg-surface p-3"
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className="block rounded-sm"
                style={{
                  inlineSize: "14px",
                  blockSize: "14px",
                  backgroundColor: SWATCH[skill.state],
                }}
              />
              <span className="font-semibold text-ink">{skill.labelAr}</span>
            </span>
            <span className="mt-1 block text-sm" style={{ color: TEXT[skill.state] }}>
              {stateLabels[skill.state]}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
