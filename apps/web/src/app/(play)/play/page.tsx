"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NourCharacter, type NourState } from "@/components/child/NourCharacter";
import { SessionDots } from "@/components/child/SessionDots";
import {
  ListenPoint,
  MatchPair,
  SayIt,
  SortCategory,
  StoryMoment,
} from "@/components/play/games";
import { Celebration, ClosingScene, StartScreen } from "@/components/play/scenes";
import type { AttemptResult, GameProps, PlayLabels } from "@/components/play/shared";
import { CATEGORY_ORDER, type SkillCategory } from "@/content/curriculum";
import {
  DEFAULT_PROFILE,
  interActivityPauseMs,
  type AccessibilityProfile,
} from "@/lib/interaction";
import { MODALITY_OF, type ManifestActivity, type SessionManifest } from "@/lib/manifest";
import { MemoryOutboxStorage, Outbox, attemptKey } from "@/lib/outbox";
import { endSession, playPoster } from "@/lib/play-client";
import { loadSession } from "@/lib/play-session";
import { recordedPromptLevel, rungAt, type Rung } from "@/lib/prompt-ladder";
import { createVoice, type Voice } from "@/lib/voice";

/**
 * The child's play screen.
 *
 * Everything here follows from one sentence in docs/04e §C13: **there is no
 * failure state**. That is why:
 *
 * * there is no visible timer — the prompt ladder is on a clock the child
 *   cannot see, so waiting is never running out of time;
 * * there is no disabled choice and no "wrong" styling — nothing a child can
 *   tap is an error;
 * * every attempt is written to the outbox before it is posted — a dropped
 *   connection is not something a child should ever find out about;
 * * the caregiver override sits beside every expressive activity permanently,
 *   rather than appearing after two failed tries, because appearing after two
 *   failed tries would mean there had been two failures;
 * * the last rung of the ladder answers for the child, so doing nothing is a
 *   valid way to answer and never a way to get stuck.
 *
 * This component owns the session's four moving parts — the clock, the voice,
 * the outbox and the manifest — and the five games own none of them. A game's
 * whole contract is to call `onAnswer`.
 */

const GAMES: Record<ManifestActivity["kind"], (props: GameProps) => React.ReactElement> = {
  listen_point: ListenPoint,
  match_pair: MatchPair,
  say_it: SayIt,
  sort_category: SortCategory,
  story_moment: StoryMoment,
};

export default function PlayPage() {
  const t = useTranslations("play");

  const [phase, setPhase] = useState<"start" | "loading" | "playing" | "closing">("start");
  const [manifest, setManifest] = useState<SessionManifest | null>(null);
  const [worlds, setWorlds] = useState<readonly SkillCategory[]>(CATEGORY_ORDER);
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [nour, setNour] = useState<NourState>("idle");
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [celebrating, setCelebrating] = useState(false);
  const [stickers, setStickers] = useState<string[]>([]);

  // The real sender. This was `async () => ({ ok: true })` — an acknowledger,
  // not a sender: every tap a child made was written to memory, marked
  // delivered, and pruned five minutes later. Nothing was ever stored.
  const outbox = useRef(new Outbox(new MemoryOutboxStorage(), playPoster));
  const voice = useRef<Voice | null>(null);
  const autoSelected = useRef<string | null>(null);
  const startedAtMs = useRef<number>(0);
  //: Guards the close against a re-render firing it twice. A second `end`
  //: would write a second `session_end` event, and the caregiver's streak is
  //: counted in sessions.
  const closed = useRef<string | null>(null);

  const profile: AccessibilityProfile = useMemo(
    () =>
      manifest
        ? {
            waitTimeMs: manifest.child.wait_time_ms,
            maxChoices: manifest.child.max_choices,
            audioRatePct: manifest.child.audio_rate_pct,
            calmMode: manifest.child.calm_mode,
          }
        : DEFAULT_PROFILE,
    [manifest],
  );

  const activities = manifest?.activities ?? [];
  const activity = activities[index];
  const ladder = rungAt(elapsed, profile.waitTimeMs);
  const rung: Rung = ladder.rung;

  const labels: PlayLabels = useMemo(
    () => ({
      replay: t("replay"),
      mic: t("mic"),
      override: t("override"),
      sayTogether: t("sayTogether"),
      next: t("next"),
    }),
    [t],
  );

  /* ------------------------------- the clock ----------------------------- */

  // Started only after the caregiver's tap, so a screen left open on a table
  // never advances a ladder for a child who is not there. Stopped during the
  // celebration, so the 800ms of calm is not also 800ms of ladder.
  useEffect(() => {
    if (phase !== "playing" || celebrating) return undefined;
    const timer = window.setInterval(() => setElapsed((value) => value + 250), 250);
    return () => window.clearInterval(timer);
  }, [phase, celebrating, index]);

  // Wake lock: an 8-second wait must not be interrupted by the screen dimming.
  useEffect(() => {
    if (phase !== "playing") return undefined;
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: "screen") => Promise<{ release: () => void }> };
    };
    let sentinel: { release: () => void } | null = null;
    nav.wakeLock
      ?.request("screen")
      .then((lock) => {
        sentinel = lock;
      })
      // A refused wake lock is not an error the session should stop for.
      .catch(() => undefined);
    return () => sentinel?.release();
  }, [phase]);

  /* ------------------------------- the voice ----------------------------- */

  const say = useCallback(
    (text: string, audioUrl?: string) => {
      setNour("speaking");
      void voice.current?.speak(text, audioUrl).finally(() => setNour("idle"));
    },
    [],
  );

  // Nour speaks the instruction when the activity opens, and again at each rung
  // — identical audio, identical rate. docs/04e §C13: a rephrased instruction
  // is a new comprehension task at the moment the child is already struggling.
  useEffect(() => {
    if (phase !== "playing" || celebrating || !activity) return;
    say(activity.instruction_ar, activity.instruction_audio);
    // `rung` is in the dependency list on purpose: every rung re-speaks the
    // same line. `activity.id` rather than `activity` so a re-render with an
    // equal-but-new object does not restart the audio mid-sentence.
  }, [phase, celebrating, activity?.id, rung]);

  /* ------------------------------ recording ------------------------------ */

  const advance = useCallback(() => {
    setCelebrating(true);
    setNour("celebrating");
    // 800ms of calm between activities (1200ms in calm mode). Processing time,
    // not a transition.
    window.setTimeout(() => {
      setCelebrating(false);
      setNour("idle");
      setChosenId(null);
      setElapsed(0);
      autoSelected.current = null;
      setIndex((value) => {
        const next = value + 1;
        if (next >= activities.length) setPhase("closing");
        return next;
      });
    }, interActivityPauseMs(profile));
  }, [profile, activities.length]);

  const record = useCallback(
    async (selectedSkillId: string | null, result: AttemptResult) => {
      if (!activity || celebrating) return;
      setChosenId(selectedSkillId);
      setStickers((collected) => [...collected, activity.skill_id]);
      const sessionId = manifest?.session_id ?? "local";
      const key = attemptKey(sessionId, activity.id, 1);
      // Written locally FIRST, with a deterministic key. Then posted. The body
      // is `AttemptIn` from `play/schemas.py`, field for field — `skill_code`
      // rather than `skill_id`, because the manifest carries curriculum codes
      // and the database's uuids are the server's business.
      await outbox.current.enqueue(
        `/play/sessions/${sessionId}/attempts`,
        {
          activity_code: `${activity.kind}:${activity.skill_id}`,
          skill_code: activity.skill_id,
          selected_skill_code: selectedSkillId,
          result,
          prompt_level: recordedPromptLevel(rung),
          modality: MODALITY_OF[activity.kind],
          choice_count: activity.choices.length,
          client_ts: new Date().toISOString(),
          idempotency_key: key,
        },
        key,
      );
      // A locally-built session has no server row, so there is nothing to drain
      // to. The attempts stay in the outbox rather than being posted at a 404
      // until the end of time.
      if (manifest && !manifest.local) await outbox.current.drain();
      advance();
    },
    [activity, celebrating, manifest, rung, advance],
  );

  // The last rung answers for the child. This is the line that makes "doing
  // nothing" a valid response rather than a dead end, and it is why the ladder
  // has no rung after `full_model`.
  useEffect(() => {
    if (phase !== "playing" || celebrating || !activity) return undefined;
    if (ladder.autoSelectAfterMs === null) return undefined;
    if (autoSelected.current === activity.id) return undefined;
    const timer = window.setTimeout(() => {
      autoSelected.current = activity.id;
      const correct = activity.choices.find((choice) => choice.correct);
      void record(correct?.skill_id ?? null, "correct");
    }, ladder.autoSelectAfterMs);
    return () => window.clearTimeout(timer);
  }, [phase, celebrating, activity, ladder.autoSelectAfterMs, record]);

  // Closing the session is what puts it on the caregiver's dashboard: the API
  // writes the one `session_end` event the whole rollup is built from. A drain
  // first, so the last attempt is on file before the totals are computed from
  // it — the server counts rows, not what the client claims.
  useEffect(() => {
    if (phase !== "closing") return;
    const sessionId = manifest?.session_id;
    if (!manifest || manifest.local || !sessionId) return;
    if (closed.current === sessionId) return;
    closed.current = sessionId;
    const minutes = Math.max(
      1,
      Math.round((Date.now() - (startedAtMs.current || Date.now())) / 60_000),
    );
    void outbox.current
      .drain()
      .then(() => endSession(sessionId, { minutes }))
      // Nothing here is a failure a child is told about. An unclosed session is
      // a dashboard one session out of date, and the nightly rebuild fixes it.
      .catch(() => undefined);
  }, [phase, manifest]);

  /* -------------------------------- start -------------------------------- */

  const start = useCallback(async () => {
    setPhase("loading");
    // The caregiver's tap is the audio unlock, so this is the only moment a
    // voice may be created — one made earlier is one a mobile autoplay policy
    // will silence.
    const session = await loadSession({
      categories: worlds.length ? worlds : CATEGORY_ORDER,
    });
    voice.current = createVoice({
      ratePct: session.child.audio_rate_pct,
      enabled: true,
    });
    setManifest(session);
    startedAtMs.current = Date.now();
    closed.current = null;
    setIndex(0);
    setElapsed(0);
    setStickers([]);
    autoSelected.current = null;
    setPhase("playing");
  }, [worlds]);

  const restart = useCallback(() => {
    voice.current?.stop();
    setManifest(null);
    setPhase("start");
  }, []);

  const toggleWorld = useCallback((category: SkillCategory) => {
    setWorlds((current) =>
      current.includes(category)
        ? // Never empty. Deselecting the last world would mean a session with no
          // content, and the button that produces it should not exist.
          current.length === 1
          ? current
          : current.filter((item) => item !== category)
        : [...current, category],
    );
  }, []);

  /* -------------------------------- render ------------------------------- */

  if (phase === "start") {
    return (
      <StartScreen
        title={t("title")}
        hint={t("startHint")}
        startLabel={t("start")}
        pickLabel={t("pickWorld")}
        worldLabels={{
          colors: t("world.colors"),
          body_parts: t("world.body_parts"),
          social: t("world.social"),
          household: t("world.household"),
          numbers: t("world.numbers"),
          letters: t("world.letters"),
        }}
        selected={worlds}
        onToggleWorld={toggleWorld}
        onStart={() => void start()}
      />
    );
  }

  if (phase === "loading") {
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

  if (phase === "closing" || !activity) {
    return (
      <ClosingScene
        message={t("closing")}
        stickers={stickers}
        againLabel={t("again")}
        onAgain={restart}
      />
    );
  }

  const Game = GAMES[activity.kind];
  const praise = t(`praise.${index % 4}`);

  return (
    <div data-testid="play-screen" data-rung={rung} data-kind={activity.kind} className="min-h-screen">
      <SessionDots total={activities.length} done={index} />

      <div className="flex flex-col items-center gap-5 p-3">
        <NourCharacter state={nour} size={112} />

        {celebrating ? (
          <Celebration praise={praise} />
        ) : (
          <Game
            activity={activity}
            highlight={ladder.highlight}
            chosenId={chosenId}
            labels={labels}
            // 104px, so that at a 320px phone two cards plus their 20px gaps,
            // borders and padding fit side by side. That is the width the
            // touch-target assertion actually runs at, and the width at which
            // two choices stop being comparable if they get any wider.
            cardSize={104}
            onAnswer={(selected, result) => void record(selected, result)}
            onReplay={() => say(activity.instruction_ar, activity.instruction_audio)}
          />
        )}
      </div>
    </div>
  );
}
