"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/ui/Card";
import { CAREGIVER_TOUCH_TARGET_PX } from "@/lib/interaction";

/**
 * The caregiver's starting questionnaire.
 *
 * One question per screen, four large buttons, and the concrete example under
 * every question — docs/04e §C12: a parent can reliably answer "if you put a
 * red cup and a blue cup down and ask for the red one, does he pick it up?" and
 * cannot reliably answer "does he understand colour concepts?".
 *
 * Nothing here is scored on the client. The answers are posted one at a time
 * (so a closed tab loses at most the current one) and the derivation — the
 * priors, the support level, the comfortable duration — happens on the server
 * at `finalise`, which is also where the child's learner state is created.
 *
 * The watermark is rendered whenever the server sends one. A placeholder
 * instrument that looks exactly like a reviewed one is the failure it exists to
 * prevent, and hiding it here would put the failure back.
 */

interface Option {
  id: string;
  label_ar: string;
}

interface Question {
  id: string;
  area: string;
  prompt_ar: string;
  example_ar: string;
  options: Option[];
}

interface State {
  assessment_id: string;
  status: string;
  answered: number;
  total: number;
  complete: boolean;
  next_questions: Question[];
  watermark: string;
}

async function post<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const response = await fetch(`/api/starting/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function StartingAssessment({ childId }: { childId: string }) {
  const t = useTranslations("starting");
  const te = useTranslations("errors");
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [finished, setFinished] = useState(false);

  const begin = useCallback(async () => {
    const started = await post<State>("start", { child_id: childId });
    if (started === null) setFailed(true);
    else setState(started);
  }, [childId]);

  useEffect(() => {
    void begin();
  }, [begin]);

  const answer = async (questionId: string, answerId: string) => {
    if (!state || busy) return;
    setBusy(true);
    const next = await post<State>(`${state.assessment_id}/answers`, {
      question_id: questionId,
      answer_id: answerId,
    });
    setBusy(false);
    if (next === null) {
      setFailed(true);
      return;
    }
    setState(next);
  };

  const finalise = async () => {
    if (!state || busy) return;
    setBusy(true);
    const done = await post<unknown>(`${state.assessment_id}/finalise`, {});
    setBusy(false);
    if (done === null) setFailed(true);
    else setFinished(true);
  };

  if (failed) {
    return (
      <Card>
        <p role="alert" className="text-attention">
          {te("network")}
        </p>
        <button
          type="button"
          onClick={() => {
            setFailed(false);
            void begin();
          }}
          className="mt-4 rounded-pill bg-primary px-6 py-3 text-on-primary"
          style={{ minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px` }}
        >
          {t("finish")}
        </button>
      </Card>
    );
  }

  if (finished) {
    return (
      <Card data-testid="starting-done">
        <h1 className="text-2xl font-semibold">{t("done")}</h1>
        <p className="mt-2 text-ink-muted">{t("doneBody")}</p>
        <a
          href="/children"
          data-testid="starting-continue"
          className="mt-6 inline-block rounded-pill bg-primary px-6 py-3 text-on-primary"
          style={{ minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px` }}
        >
          {t("startPlaying")}
        </a>
      </Card>
    );
  }

  if (!state) {
    return <Card>{t("lede")}</Card>;
  }

  const question = state.next_questions[0];

  return (
    <div data-testid="starting-assessment" data-answered={state.answered}>
      <h1 className="mb-1 text-2xl font-semibold">{t("title")}</h1>
      <p className="mb-4 text-ink-muted">{t("lede")}</p>
      {state.watermark ? (
        <p
          data-testid="starting-watermark"
          className="mb-4 rounded-md border border-attention p-3 text-attention"
        >
          {state.watermark}
        </p>
      ) : null}

      {/* Only ever shrinks. docs/04b: a progress line that grows reads as the
          end receding, which is worse than none at all. */}
      <p className="mb-4" data-testid="starting-progress">
        {t("progress", { answered: state.answered, total: state.total })}
      </p>

      {question ? (
        <Card key={question.id}>
          <h2 className="text-xl font-semibold">{question.prompt_ar}</h2>
          <p className="mt-2 text-ink-muted">{question.example_ar}</p>
          <div className="mt-5 grid gap-3">
            {question.options.map((option) => (
              <button
                key={option.id}
                type="button"
                data-testid={`answer-${option.id}`}
                disabled={busy}
                onClick={() => void answer(question.id, option.id)}
                className="rounded-md border-2 border-primary-soft px-5 py-4 text-start text-lg disabled:opacity-50"
                style={{ minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px` }}
              >
                {option.label_ar}
              </button>
            ))}
          </div>
        </Card>
      ) : null}

      {state.complete ? (
        <button
          type="button"
          data-testid="starting-finalise"
          disabled={busy}
          onClick={() => void finalise()}
          className="mt-6 rounded-pill bg-primary px-8 py-4 text-xl text-on-primary disabled:opacity-50"
          style={{ minBlockSize: `${CAREGIVER_TOUCH_TARGET_PX}px` }}
        >
          {t("finish")}
        </button>
      ) : null}
    </div>
  );
}
