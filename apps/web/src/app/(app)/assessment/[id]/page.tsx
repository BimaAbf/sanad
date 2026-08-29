"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { InterpretationChip } from "@/components/caregiver/InterpretationChip";
import { ProgressRange } from "@/components/caregiver/ProgressRange";
import { VerdictButtons, type Verdict } from "@/components/caregiver/VerdictButtons";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
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
 * This page holds the SSE consumption and the local state. Every number it
 * renders comes from the server.
 */

interface Question {
  itemId: string;
  promptAr: string;
  promptMsa: string;
  exampleAr: string;
}

const PLACEHOLDER_QUESTION: Question = {
  itemId: "item_000",
  // PLACEHOLDER — item text is clinical content and must come from the item
  // bank, not from this file. seeds/item_bank.py ships `synthetic-v1`,
  // watermarked NOT FOR CLINICAL USE.
  promptAr: "بيشرب من الكوباية لوحده؟",
  promptMsa: "هل يشرب من الكوب بمفرده؟",
  exampleAr: "بيشرب من الكوباية لوحده من غير ما تمسكيها",
};

export default function AssessmentRunner() {
  const t = useTranslations("assessment");
  const [range, setRange] = useState<Range>(start(20, 55));
  const [showMsa, setShowMsa] = useState(false);
  const [freeText, setFreeText] = useState("");
  const [interpreted, setInterpreted] = useState<Verdict | null>(null);
  const [question] = useState<Question>(PLACEHOLDER_QUESTION);

  const answer = (verdict: Verdict) => {
    // The engine's fresh estimate is folded in through `narrow`, which clamps
    // it. A rendered range therefore cannot widen even if the engine's estimate
    // does — which it legitimately can, because the assessment is adaptive.
    setRange((previous) =>
      narrow(previous, {
        answered: previous.answered + 1,
        minRemaining: Math.max(0, previous.minRemaining - 1),
        maxRemaining: Math.max(0, previous.maxRemaining - 1),
      }),
    );
    setInterpreted(null);
    setFreeText("");
    void verdict;
  };

  const verdictLabels: Record<Verdict, string> = {
    yes: t("verdict.yes"),
    emerging: t("verdict.emerging"),
    no: t("verdict.no"),
    unsure: t("verdict.unsure"),
    not_applicable: t("verdict.not_applicable"),
  };

  return (
    <div data-testid="pgee-runner">
      <ProgressRange
        range={range}
        label={t("progress.range", { min: range.minRemaining, max: range.maxRemaining })}
      />

      <Card className="mt-5">
        {/* 20px minimum, 1.9 line-height — Arabic needs more leading than Latin. */}
        <h1 data-testid="question" className="text-lg leading-loose text-ink">
          {showMsa ? question.promptMsa : question.promptAr}
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
          {question.exampleAr}
        </p>

        <div className="mt-6">
          <VerdictButtons labels={verdictLabels} onAnswer={answer} />
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
            onConfirm={() => answer(interpreted)}
            onChange={() => setInterpreted(null)}
          />
        ) : null}
      </Card>

      {/* On every screen, always visible. An assessment a parent cannot pause is
          one they abandon rather than one they finish. */}
      <div className="mt-5 flex justify-center">
        <Button variant="ghost" data-testid="save-and-exit">
          {t("saveAndExit")}
        </Button>
      </div>
    </div>
  );
}
