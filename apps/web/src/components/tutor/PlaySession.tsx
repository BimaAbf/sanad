"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { NourCharacter, type NourState } from "@/components/child/NourCharacter";
import { SessionDots } from "@/components/child/SessionDots";
import { ActivityView } from "@/components/tutor/activities";
import { interActivityPauseMs, type AccessibilityProfile } from "@/lib/interaction";
import {
  INITIAL,
  canAnswer,
  currentActivity,
  reduce,
  shouldCelebrate,
  shouldRetry,
} from "@/lib/activity-machine";
import {
  endSession,
  nextActivity,
  responseKey,
  startSession,
  submitResponse,
  type PromptLevel,
  type ResponsePayload,
  type SessionResult,
} from "@/lib/tutor";
import { createVoice, type Voice } from "@/lib/voice";

/**
 * The child's session, driven entirely by the server.
 *
 * The whole component is a loop over four calls — start, next, respond, end —
 * and the important thing about it is what it does NOT contain:
 *
 * * no comparison of a tapped option against a correct one, because the correct
 *   one is not in anything this component receives;
 * * no celebration that is not attached to `result.correct` from the server;
 * * no client-side sequence of activities, because there is no sequence — each
 *   activity is a fresh teaching decision taken after the previous answer was
 *   recorded;
 * * no local fallback session. The previous version of this screen fell back to
 *   a bundled curriculum whenever the API was slow, which meant a demo against
 *   a broken backend looked exactly like a demo against a working one and
 *   persisted nothing. A failure here is a retry, visible to the caregiver and
 *   invisible to the child.
 *
 * The prompt ladder is on a clock the child cannot see, and its last rung
 * submits `no_response` rather than answering for them. That is the one
 * behaviour change from the old screen worth stating plainly: the old ladder
 * auto-selected the CORRECT choice and recorded it as `correct`, which put an
 * answer the child never gave into their record and paid a star for it.
 */

const RUNG_ONE = 1;
const RUNG_TWO = 2;

export function PlaySession({
  childId,
  profile,
}: {
  childId: string;
  profile: AccessibilityProfile;
}) {
  const t = useTranslations("play");
  const [state, dispatch] = useReducer(reduce, INITIAL);
  const [session, setSession] = useState<string | null>(null);
  const [stars, setStars] = useState(0);
  const [summary, setSummary] = useState<SessionResult | null>(null);
  const [nour, setNour] = useState<NourState>("idle");
  const [rung, setRung] = useState(0);
  const [answered, setAnswered] = useState(0);

  const voice = useRef<Voice | null>(null);
  const startedAt = useRef<number>(0);
  const shownAt = useRef<number>(0);
  const closing = useRef(false);

  const activity = currentActivity(state);
  const labels = {
    replay: t("replay"),
    mic: t("mic"),
    override: t("micUnavailable"),
    confirm: t("override"),
    done: t("done"),
  };

  /* ------------------------------ the loop ------------------------------- */

  const loadNext = useCallback(
    async (sessionId: string) => {
      const reply = await nextActivity(sessionId);
      if (!reply.ok) {
        dispatch({ type: "ERROR", messageAr: reply.messageAr });
        return;
      }
      if (reply.value.session_finished) {
        dispatch({ type: "SESSION_OVER" });
        return;
      }
      setRung(0);
      shownAt.current = Date.now();
      dispatch({ type: "ACTIVITY_LOADED", activity: reply.value });
    },
    [],
  );

  const begin = useCallback(async () => {
    dispatch({ type: "START" });
    // The caregiver's tap is the audio unlock, so this is the only moment a
    // voice may be created — one made earlier is one a mobile autoplay policy
    // will silence.
    voice.current = createVoice({ ratePct: profile.audioRatePct, enabled: true });
    startedAt.current = Date.now();
    closing.current = false;
    setStars(0);
    setAnswered(0);
    setSummary(null);

    const opened = await startSession(childId);
    if (!opened.ok) {
      dispatch({ type: "ERROR", messageAr: opened.messageAr });
      return;
    }
    setSession(opened.value.session_id);
    await loadNext(opened.value.session_id);
  }, [childId, loadNext, profile.audioRatePct]);

  const answer = useCallback(
    async (response: ResponsePayload) => {
      if (!session || !activity?.activity_id) return;
      // The client-side half of "one tap, one attempt". The idempotency key is
      // the server-side half, and a network retry never reaches this guard.
      if (!canAnswer(state)) return;
      dispatch({ type: "SUBMIT" });

      const level: PromptLevel =
        rung >= RUNG_TWO ? "partial_verbal" : rung === RUNG_ONE ? "gestural" : "independent";
      const reply = await submitResponse(session, {
        activityId: activity.activity_id,
        response,
        idempotencyKey: responseKey(session, activity.activity_id),
        latencyMs: Math.max(0, Date.now() - shownAt.current),
        promptLevel: level,
      });
      if (!reply.ok) {
        // Nothing is celebrated, nothing is counted, and the activity stays on
        // screen. A failed submission must never look like a success.
        dispatch({ type: "ERROR", messageAr: reply.messageAr });
        return;
      }
      setStars(reply.value.stars_total);
      setAnswered((count) => count + 1);
      dispatch({ type: "RESULT", result: reply.value });
    },
    [activity, rung, session, state],
  );

  /* ------------------------------ the clock ------------------------------ */

  // The prompt ladder. Two rungs of visible help, then the activity is recorded
  // as no-response and the session moves on — the child is never stuck, and
  // nothing is entered that they did not do.
  useEffect(() => {
    if (state.phase !== "ready" && state.phase !== "answering") return undefined;
    const wait = profile.waitTimeMs;
    const timers = [
      window.setTimeout(() => setRung(RUNG_ONE), wait),
      window.setTimeout(() => setRung(RUNG_TWO), wait * 2),
      window.setTimeout(() => void answer({ kind: "no_response" }), wait * 3),
    ];
    return () => timers.forEach(window.clearTimeout);
  }, [state.phase, activity?.activity_id, profile.waitTimeMs, answer]);

  // Nour speaks the instruction when the activity opens, and again at each
  // rung — identical audio, identical rate. docs/04e §C13: a rephrased
  // instruction is a new comprehension task at the moment the child is already
  // struggling.
  useEffect(() => {
    if (!activity || state.phase === "loading" || state.phase === "submitting") return;
    setNour("speaking");
    void voice.current
      ?.speak(activity.presentation.instruction_ar)
      .finally(() => setNour("idle"));
    if (state.phase === "instruction") {
      const timer = window.setTimeout(() => dispatch({ type: "INSTRUCTION_DONE" }), 400);
      return () => window.clearTimeout(timer);
    }
    return undefined;
    // `rung` is in the dependency list on purpose: every rung of the ladder
    // re-speaks the SAME line. `activity.activity_id` rather than `activity`,
    // so a re-render with an equal-but-new object does not restart the audio
    // mid-sentence.
  }, [activity?.activity_id, state.phase, rung]);

  // The pause after a verdict: 800ms of calm, 1200ms in calm mode. Processing
  // time, not a transition.
  useEffect(() => {
    if (state.phase !== "result" || !session) return undefined;
    setNour(state.result.correct ? "celebrating" : "idle");
    const timer = window.setTimeout(() => {
      setNour("idle");
      dispatch({ type: "CONTINUE" });
      void loadNext(session);
    }, interActivityPauseMs(profile));
    return () => window.clearTimeout(timer);
  }, [state, session, profile, loadNext]);

  // Closing. Guarded against a re-render firing it twice — a second `end` would
  // write a second completion bonus if the key did not already prevent it, and
  // would certainly write a second summary.
  useEffect(() => {
    if (state.phase !== "closing" || !session || closing.current) return;
    closing.current = true;
    const minutes = Math.max(1, Math.round((Date.now() - startedAt.current) / 60_000));
    void endSession(session, minutes).then((reply) => {
      dispatch({ type: "CLOSED", summary: reply.ok ? reply.value : null });
      if (reply.ok) setStars(reply.value.stars_total);
    });
  }, [state.phase, session]);

  /* ------------------------------- render -------------------------------- */

  if (state.phase === "idle") {
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <div className="flex flex-col items-center gap-6">
          <NourCharacter state="idle" size={168} />
          <h1 className="text-3xl font-semibold">{t("title")}</h1>
          <p className="text-lg text-ink-muted">{t("startHint")}</p>
          <button
            type="button"
            data-testid="play-start"
            onClick={() => void begin()}
            className="rounded-pill bg-primary px-10 py-5 text-2xl text-on-primary"
            style={{ minBlockSize: "88px" }}
          >
            {t("start")}
          </button>
        </div>
      </div>
    );
  }

  if (state.phase === "loading" && !activity) {
    // A skeleton, never a spinner (docs/06 §3) — and Nour, so the child is
    // looking at the same character they were looking at a second ago.
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <div className="flex flex-col items-center gap-5">
          <NourCharacter state="idle" size={148} />
          <p className="text-lg text-ink-muted">{t("loading")}</p>
        </div>
      </div>
    );
  }

  if (state.phase === "finished") {
    return (
      <ClosingScene
        stars={stars}
        summary={summary ?? state.summary}
        onAgain={() => {
          setSession(null);
          dispatch({ type: "START" });
          void begin();
        }}
      />
    );
  }

  if (state.phase === "closing") {
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <NourCharacter state="celebrating" size={148} />
      </div>
    );
  }

  return (
    <div
      data-testid="play-screen"
      data-phase={state.phase}
      data-rung={rung}
      data-activity-type={activity?.activity_type ?? ""}
      // The tracing guide, as the server sent it. Published so an automated
      // test can draw ON the guide rather than at coordinates it guessed —
      // a test that traced from memory would pass while the guide moved.
      data-reference-path={
        activity?.presentation.reference_path?.length
          ? JSON.stringify(activity.presentation.reference_path)
          : undefined
      }
      className="min-h-screen"
    >
      <SessionDots total={Math.max(answered + 1, 1)} done={answered} />
      <div className="flex flex-col items-center gap-5 p-3">
        <NourCharacter state={nour} size={112} />

        {/* The verdict. The ONLY branch in this component that decides what a
            child sees after answering, and it reads `result.correct` — the
            server's word — and nothing else. */}
        {state.phase === "result" ? (
          <div
            data-testid="verdict"
            data-correct={String(state.result.correct)}
            data-outcome={state.result.outcome}
            className="flex flex-col items-center gap-3"
          >
            {shouldCelebrate(state) ? (
              <p data-testid="celebration" className="text-child font-semibold text-primary">
                {t("praise.0")}
              </p>
            ) : null}
            {shouldRetry(state) ? (
              <p data-testid="encouragement" className="text-child font-semibold text-ink">
                {state.result.outcome === "uncertain"
                  ? t("encourage.2")
                  : t("encourage.0")}
              </p>
            ) : null}
            {state.result.reward_delta > 0 ? (
              <p data-testid="stars-earned" className="text-2xl">
                {"⭐".repeat(state.result.reward_delta)}
              </p>
            ) : null}
          </div>
        ) : null}

        {state.phase === "error" ? (
          <div
            data-testid="play-error"
            role="alert"
            className="flex flex-col items-center gap-4"
          >
            {/* Deliberately not an apology and not an explanation. There is no
                failure state for the child; the retry is for the adult. */}
            <p className="text-lg text-ink-muted">{t("encourage.1")}</p>
            <button
              type="button"
              data-testid="play-retry"
              onClick={() => {
                dispatch({ type: "RETRY" });
                if (session && !currentActivity(state)) void loadNext(session);
              }}
              className="rounded-pill bg-accent-soft px-6 py-3 text-lg"
              style={{ minBlockSize: "48px" }}
            >
              {t("again")}
            </button>
          </div>
        ) : null}

        {activity && state.phase !== "result" && state.phase !== "error" ? (
          <ActivityView
            activity={activity}
            enabled={canAnswer(state)}
            hint={rung >= RUNG_ONE}
            labels={labels}
            onSubmit={(response) => void answer(response)}
            onReplay={() => {
              setNour("speaking");
              void voice.current
                ?.speak(activity.presentation.instruction_ar)
                .finally(() => setNour("idle"));
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

function ClosingScene({
  stars,
  summary,
  onAgain,
}: {
  stars: number;
  summary: SessionResult | null;
  onAgain: () => void;
}) {
  const t = useTranslations("play");
  return (
    <div
      data-testid="closing-scene"
      className="grid min-h-screen place-items-center p-6 text-center"
    >
      <div className="flex flex-col items-center gap-6">
        <NourCharacter state="celebrating" size={168} />
        <p className="text-3xl font-semibold">{t("closing")}</p>
        {/* Stars and skills. No accuracy, no ratio, no comparison — docs/04e
            §C13 has no failure state, and "4 out of 7" is one however it is
            phrased. */}
        <p data-testid="stars-total" className="text-4xl">
          ⭐ {stars}
        </p>
        {summary && summary.skills_practised_ar.length > 0 ? (
          <ul data-testid="skills-practised" className="flex flex-wrap justify-center gap-3">
            {summary.skills_practised_ar.map((label) => (
              <li key={label} className="rounded-pill bg-accent-soft px-4 py-2 text-lg">
                {label}
              </li>
            ))}
          </ul>
        ) : null}
        {summary && summary.achievements_unlocked.length > 0 ? (
          <p data-testid="achievements" className="text-xl">
            🏅 {summary.achievements_unlocked.length}
          </p>
        ) : null}
        <button
          type="button"
          data-testid="play-again"
          onClick={onAgain}
          className="rounded-pill bg-primary px-10 py-5 text-2xl text-on-primary"
          style={{ minBlockSize: "88px" }}
        >
          {t("again")}
        </button>
      </div>
    </div>
  );
}
