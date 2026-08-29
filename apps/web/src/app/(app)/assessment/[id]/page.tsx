"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { InterpretationChip } from "@/components/caregiver/InterpretationChip";
import { ProgressRange } from "@/components/caregiver/ProgressRange";
import { VerdictButtons, type Verdict } from "@/components/caregiver/VerdictButtons";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  answerItem,
  finaliseAssessment,
  startAssessment,
  type ApiVerdict,
  type AssessmentItem,
  type AssessmentState,
} from "@/lib/assessment-client";
import { narrow, start, type Range } from "@/lib/progress-range";

/**
 * The PGEE runner — "the most important screen in the product" (docs/04e §C12).
 *
 * The anatomy is the doc's, top to bottom, and the order is load-bearing:
 *
 *   1. narrowing progress range     never widens; see lib/progress-range.ts
 *   2. the question                 Egyptian Arabic, MSA available on tap
 *   3. a concrete example           parents cannot answer abstract questions
 *                                   about their own child reliably — the
 *                                   example is what makes the answer valid
 *   4. three big buttons            ALWAYS present, even with free text
 *   5. free text + mic              secondary, never the default
 *   6. a confirmable chip           one tap to correct an interpretation
 *   7. save and continue later      on every screen, always visible
 *
 * There is no score, no percentage and no colour-coding of answers anywhere in
 * this flow. docs/04e calls anxiety management a design requirement; a parent
 * fifty questions into an assessment about their own child must not be able to
 * read a running verdict off the screen.
 *
 * The questions and the answers are now the API's. This screen previously held
 * one hardcoded question and discarded every answer with `void verdict`, which
 * meant no assessment was ever recorded and `/child/[id]/journey` answered
 * `insufficient_data` for every child forever.
 *
 * Unlike the child app, a failure here is SHOWN. The child must never find out
 * that the network dropped; a caregiver answering fifty questions must, because
 * the alternative is letting them finish an assessment that was never saved.
 */

/**
 * The UI's fifth verdict has no `response_verdict` value: "unsure" is not an
 * observation. `skipped` is its meaning in the engine — it breaks a consecutive
 * run without contributing to it, so an unsure answer cannot inflate a ceiling.
 */
const API_VERDICT: Record<Verdict, ApiVerdict> = {
  yes: "yes",
  emerging: "emerging",
  no: "no",
  not_applicable: "not_applicable",
  unsure: "skipped",
};

export default function AssessmentRunner() {
  const t = useTranslations("assessment");
  const [state, setState] = useState<AssessmentState | null>(null);
  const [range, setRange] = useState<Range>(start(0, 0));
  const [showMsa, setShowMsa] = useState(false);
  const [freeText, setFreeText] = useState("");
  const [interpreted, setInterpreted] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState(true);
  const [unsaved, setUnsaved] = useState(false);

  /**
   * Fold a server state into the display.
   *
   * `remaining_estimate` is the engine's honest count of unanswered items in
   * incomplete domains — it can legitimately RISE as the engine widens a
   * search. `narrow` clamps the displayed range so it cannot, which is the
   * docs/04e §C12 rule: the end of an assessment never moves further away while
   * a parent watches.
   */
  const apply = useCallback((next: AssessmentState) => {
    setState(next);
    setRange((previous) =>
      narrow(previous, {
        answered: next.answered,
        minRemaining: Math.min(next.next_items.length, next.remaining_estimate),
        maxRemaining: next.remaining_estimate,
      }),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    void startAssessment().then((next) => {
      if (cancelled) return;
      if (next) {
        // The first server estimate seeds the range rather than narrowing an
        // invented one: `start(20, 55)` was a guess, and a guessed ceiling that
        // the real estimate then exceeds is a range that would have to widen.
        setRange(start(Math.min(next.next_items.length, next.remaining_estimate), next.remaining_estimate));
        apply(next);
      } else {
        setUnsaved(true);
      }
      setBusy(false);
    });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const question: AssessmentItem | undefined = state?.next_items[0];

  const answer = useCallback(
    async (verdict: Verdict) => {
      if (!state || !question || busy) return;
      setBusy(true);
      setInterpreted(null);
      setFreeText("");
      setShowMsa(false);
      const next = await answerItem(state.assessment_id, question.item_id, API_VERDICT[verdict]);
      if (next) {
        setUnsaved(false);
        apply(next);
        // Finalising is what writes the domain scores the journey chart is
        // drawn from. An assessment that is answered to the end but never
        // finalised is one that never reaches the caregiver.
        if (next.complete) await finaliseAssessment(next.assessment_id);
      } else {
        // Not advanced. The same question stays on screen, which is the honest
        // state: this answer is not on file.
        setUnsaved(true);
      }
      setBusy(false);
    },
    [state, question, busy, apply],
  );

  const verdictLabels: Record<Verdict, string> = {
    yes: t("verdict.yes"),
    emerging: t("verdict.emerging"),
    no: t("verdict.no"),
    unsure: t("verdict.unsure"),
    not_applicable: t("verdict.not_applicable"),
  };

  if (!state && busy) {
    return (
      <div data-testid="pgee-runner">
        <Card className="mt-5">
          <p className="text-ink-muted">{t("loading")}</p>
        </Card>
      </div>
    );
  }

  if (state?.complete || (state && !question)) {
    return (
      <div data-testid="pgee-runner">
        <Card className="mt-5">
          <p data-testid="assessment-done" className="text-lg text-ink">
            {t("done")}
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div data-testid="pgee-runner">
      <ProgressRange
        range={range}
        label={t("progress.range", { min: range.minRemaining, max: range.maxRemaining })}
      />

      {/* The bank's own provenance warning, carried onto the screen. Every
          number derived from `synthetic-v1` means nothing about a real child,
          and a placeholder bank that looks like a real one is the failure this
          line exists to prevent. Empty once a reviewed bank ships. */}
      {state?.bank_watermark ? (
        <p data-testid="bank-watermark" className="mt-3 rounded-md bg-surface-alt p-3 text-sm text-ink-muted">
          {t("placeholderBank")}
        </p>
      ) : null}

      {unsaved ? (
        <p data-testid="not-saved" role="status" className="mt-3 rounded-md bg-surface-alt p-3 text-ink">
          {t("notSaved")}
        </p>
      ) : null}

      <Card className="mt-5">
        {/* 20px minimum, 1.9 line-height — Arabic needs more leading than Latin. */}
        <h1 data-testid="question" className="text-lg leading-loose text-ink">
          {showMsa ? question?.prompt_ar_msa : question?.prompt_ar}
        </h1>
        <button
          type="button"
          data-testid="show-msa"
          onClick={() => setShowMsa((value) => !value)}
          className="mt-2 text-sm text-primary underline underline-offset-4"
        >
          {t("showMsa")}
        </button>

        <p data-testid="example" className="mt-4 rounded-md bg-surface-alt p-4 text-ink-muted">
          <span className="font-semibold">{t("example")} </span>
          {question?.example_ar}
        </p>

        <div className="mt-6">
          <VerdictButtons
            labels={verdictLabels}
            disabled={busy}
            onAnswer={(verdict) => void answer(verdict)}
          />
        </div>

        {/* Free text is SECONDARY and never the default. It is the affordance
            for a parent who wants to explain; the buttons are the fast path. */}
        <details data-testid="own-words" className="mt-6">
          <summary className="cursor-pointer text-sm text-primary">{t("ownWords")}</summary>
          <textarea
            data-testid="own-words-input"
            value={freeText}
            onChange={(event) => setFreeText(event.target.value)}
            placeholder={t("ownWordsPlaceholder")}
            rows={3}
            className="mt-3 w-full rounded-md border border-border p-3"
          />
          <Button
            variant="secondary"
            className="mt-3"
            data-testid="own-words-submit"
            onClick={() => setInterpreted("emerging")}
          >
            {t("ownWords")}
          </Button>
        </details>

        {interpreted ? (
          <InterpretationChip
            text={t("interpretation", { verdict: verdictLabels[interpreted] })}
            confirmLabel={t("interpretationConfirm")}
            changeLabel={t("interpretationChange")}
            onConfirm={() => void answer(interpreted)}
            onChange={() => setInterpreted(null)}
          />
        ) : null}
      </Card>

      {/* On every screen, always visible. An assessment a parent cannot pause is
          one they abandon rather than one they finish. Nothing has to be saved
          on the way out: every answer is already a row, and starting again
          resumes the assessment that is still open. */}
      <div className="mt-5 flex justify-center">
        <Button variant="ghost" data-testid="save-and-exit">
          {t("saveAndExit")}
        </Button>
      </div>
    </div>
  );
}
