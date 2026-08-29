"use client";

import { useEffect, useState } from "react";

import { SkillArt, LetterKeywordArt, hasKeywordArt } from "@/components/art/SkillArt";
import { CaregiverOverrideButton } from "@/components/child/CaregiverOverrideButton";
import { ChoiceCard } from "@/components/child/ChoiceCard";
import { MicButton } from "@/components/child/MicButton";
import {
  ChoiceRow,
  InstructionBubble,
  highlightFor,
  type GameProps,
} from "@/components/play/shared";
import { TOUCH_TARGET_PX } from "@/lib/interaction";
import { correctBinKey } from "@/lib/manifest";

/**
 * The five games.
 *
 * One per `activity_kind` in docs/01 §1. They are five screens rather than one
 * configurable screen because the five ask genuinely different things of a
 * child, and a single component with five branches would make it easy to give
 * one of them a failure state by accident.
 *
 * What they all obey, without exception:
 *
 * * every tappable thing is ≥ 88 px with a ≥ 20 px gap;
 * * no control is ever disabled, and nothing is ever styled as wrong;
 * * the only visual support is on the *correct* choice, and only from the
 *   second rung of the ladder;
 * * every path forward exists in at least two modalities (docs/01 P5) — tap and
 *   voice, with the caregiver override as the third when speech is involved.
 *
 * They are presentational. The clock, the ladder, the outbox and the recording
 * all live in the shell; a game's whole contract is "call `onAnswer` when the
 * child does something".
 */

/* ------------------------------- listen_point ----------------------------- */

/**
 * "وريني الأحمر" — the core activity, and about half of every session.
 *
 * Receptive: the child hears a word and points at it. It is first in every
 * session because pointing is the thing this population can do earliest and
 * most reliably, and the session should open on a success.
 */
export function ListenPoint({
  activity,
  highlight,
  chosenId,
  labels,
  cardSize,
  onAnswer,
  onReplay,
}: GameProps) {
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <InstructionBubble
        text={activity.instruction_ar}
        replayLabel={labels.replay}
        onReplay={onReplay}
      />
      <ChoiceRow>
        {activity.choices.map((choice) => (
          <ChoiceCard
            key={choice.skill_id}
            id={choice.skill_id}
            imageUrl={choice.image}
            altAr={choice.alt_ar}
            labelAr={choice.label_ar}
            size={cardSize}
            highlight={highlightFor(activity, choice.skill_id, highlight)}
            chosen={chosenId === choice.skill_id}
            onChoose={() => onAnswer(choice.skill_id, choice.correct ? "correct" : "incorrect")}
          />
        ))}
      </ChoiceRow>
    </div>
  );
}

/* -------------------------------- match_pair ------------------------------ */

/**
 * "لاقي زيها" — find the one that matches the card on top.
 *
 * Visual matching, with no listening in it at all. It is here because it is the
 * one activity a child can succeed at on a bad day: no word has to be
 * understood, no sound has to be heard through a hearing aid, nothing has to be
 * remembered. A session that includes one of these is a session that cannot be
 * derailed by a blocked ear.
 */
export function MatchPair({
  activity,
  highlight,
  chosenId,
  labels,
  cardSize,
  onAnswer,
  onReplay,
}: GameProps) {
  const card = activity.card ?? activity.choices.find((choice) => choice.correct);
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <InstructionBubble
        text={activity.instruction_ar}
        replayLabel={labels.replay}
        onReplay={onReplay}
      />
      {card ? (
        // The sample. Not a button: it is the question, and a child who taps
        // the question should not have answered it.
        <div
          data-testid="match-sample"
          className="flex flex-col items-center gap-2 rounded-lg border-4 border-dashed border-primary bg-primary-soft p-3"
        >
          <SkillArt code={card.skill_id} imageUrl={card.image} size={cardSize} />
          <span className="text-child font-semibold leading-tight text-ink">
            {card.label_ar}
          </span>
        </div>
      ) : null}
      <ChoiceRow>
        {activity.choices.map((choice) => (
          <ChoiceCard
            key={choice.skill_id}
            id={choice.skill_id}
            imageUrl={choice.image}
            altAr={choice.alt_ar}
            labelAr={choice.label_ar}
            size={cardSize}
            highlight={highlightFor(activity, choice.skill_id, highlight)}
            chosen={chosenId === choice.skill_id}
            onChoose={() => onAnswer(choice.skill_id, choice.correct ? "correct" : "incorrect")}
          />
        ))}
      </ChoiceRow>
    </div>
  );
}

/* ---------------------------------- say_it -------------------------------- */

/**
 * "قول أحمر" — the expressive activity.
 *
 * Three ways to finish it, all equal:
 *
 * * the child says the word and the recogniser hears it;
 * * the child says it and the recogniser does not, so the caregiver taps
 *   "قالها صح" — recorded as `caregiver_confirmed`, which is the truth;
 * * the child taps the picture, which is recorded as `accepted_on_effort`.
 *
 * The override is permanently visible, never revealed after two failed tries,
 * because revealing it after two failed tries would mean there had been two
 * failures. It is also the data-collection mechanism for the ASR fine-tune
 * (docs/12 §3.2), which is why it records rather than merely advancing.
 */
export function SayIt({
  activity,
  labels,
  cardSize,
  chosenId,
  onAnswer,
  onReplay,
}: GameProps) {
  const target = activity.choices[0];
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <InstructionBubble
        text={activity.instruction_ar}
        replayLabel={labels.replay}
        onReplay={onReplay}
      />
      {target ? (
        <ChoiceCard
          id={target.skill_id}
          imageUrl={target.image}
          altAr={target.alt_ar}
          labelAr={target.label_ar}
          size={Math.round(cardSize * 1.35)}
          chosen={chosenId === target.skill_id}
          // Tapping the picture is a valid way through. A child who cannot make
          // the sound today has still shown they know which thing it is.
          onChoose={() => onAnswer(target.skill_id, "accepted_on_effort")}
        />
      ) : null}
      <p className="text-lg text-ink-muted">{labels.sayTogether}</p>
      <div className="flex w-full flex-wrap items-center justify-center gap-4">
        <MicButton
          label={labels.mic}
          onCapture={() => onAnswer(activity.skill_id, "correct")}
        />
        <CaregiverOverrideButton
          label={labels.override}
          onOverride={() => onAnswer(activity.skill_id, "caregiver_confirmed")}
        />
      </div>
    </div>
  );
}

/* ----------------------------- sort_category ------------------------------ */

/**
 * "حطها في مكانها" — put the card in one of two boxes.
 *
 * Categorisation, which is the first genuinely abstract thing in the
 * curriculum: not "which one is the spoon" but "what kind of thing is a spoon".
 * Two bins, never three — the point is the category, not the search.
 *
 * Tapping a bin is the whole interaction. There is no dragging anywhere in this
 * product: a drag needs sustained pressure and a controlled path, and a child
 * who cannot complete one has been told they cannot do something they in fact
 * understand perfectly.
 */
export function SortCategory({
  activity,
  highlight,
  chosenId,
  labels,
  cardSize,
  onAnswer,
  onReplay,
}: GameProps) {
  const card = activity.choices[0];
  const correctKey = correctBinKey(activity);

  return (
    <div className="flex w-full flex-col items-center gap-5">
      <InstructionBubble
        text={activity.instruction_ar}
        replayLabel={labels.replay}
        onReplay={onReplay}
      />
      {card ? (
        <div className="flex flex-col items-center gap-2">
          <SkillArt code={card.skill_id} imageUrl={card.image} size={cardSize} />
          <span className="text-child font-semibold leading-tight text-ink">
            {card.label_ar}
          </span>
        </div>
      ) : null}
      <ChoiceRow>
        {(activity.bins ?? []).map((bin) => {
          const isCorrect = bin.key === correctKey;
          return (
            <button
              key={bin.key}
              type="button"
              // Prefixed `choice-` so the same touch-target and no-dead-end
              // assertions that cover every other tappable thing cover these.
              data-testid={`choice-bin-${bin.key}`}
              data-highlight={isCorrect ? highlight : "none"}
              onClick={() => onAnswer(bin.key, isCorrect ? "correct" : "incorrect")}
              onContextMenu={(event) => event.preventDefault()}
              className="flex flex-col items-center justify-center gap-2 rounded-lg border-4 border-dashed bg-surface-alt p-3 transition-transform duration-base"
              style={{
                minInlineSize: `${TOUCH_TARGET_PX}px`,
                minBlockSize: `${TOUCH_TARGET_PX}px`,
                borderColor:
                  chosenId === bin.key || (isCorrect && highlight !== "none")
                    ? "var(--c-primary)"
                    : "var(--c-border)",
                animationName: isCorrect && highlight !== "none" ? "sanad-pulse" : "none",
                animationDuration: "666ms",
                animationIterationCount: "infinite",
              }}
            >
              <SkillArt code={bin.art_skill_id} size={Math.round(cardSize * 0.7)} />
              <span className="text-xl font-semibold text-ink">{bin.label_ar}</span>
            </button>
          );
        })}
      </ChoiceRow>
      <span className="sr-only">{labels.next}</span>
    </div>
  );
}

/* ----------------------------- story_moment ------------------------------- */

/**
 * "شوف… أ" — two or three beats, then one choice.
 *
 * This is how a letter or a number gets introduced rather than tested. The
 * child sees the glyph, hears it, sees the keyword picture that carries its
 * sound, and only then is asked to find it. Errorless learning in its plainest
 * form: by the time there is a question, the answer has already been shown.
 *
 * The beats advance on a tap, never on a timer. A child who wants to look at
 * the lion for a minute is doing exactly what the beat is for, and no clock in
 * this product may decide otherwise.
 */
export function StoryMoment({
  activity,
  highlight,
  chosenId,
  labels,
  cardSize,
  onAnswer,
  onReplay,
}: GameProps) {
  const beats = activity.beats ?? [];
  const [beat, setBeat] = useState(0);
  const done = beat >= beats.length;

  // A new activity starts at its first beat. Without this a second story in the
  // same session would open already finished, because the component is reused.
  useEffect(() => setBeat(0), [activity.id]);

  const current = beats[beat];
  const artCode = current?.art_skill_id ?? activity.skill_id;
  const showKeyword = Boolean(current?.show_keyword) && hasKeywordArt(artCode);

  if (!done && current) {
    return (
      <div className="flex w-full flex-col items-center gap-5">
        {/* The beat's own line, in the same bubble and with the same speaker
            button as every other screen — so "hear it again" is in one place
            across all five games, including the one that is not a question. */}
        <InstructionBubble
          text={current.text_ar}
          replayLabel={labels.replay}
          onReplay={onReplay}
        />
        <button
          type="button"
          data-testid="story-beat"
          data-beat={beat}
          onClick={() => setBeat((value) => value + 1)}
          onContextMenu={(event) => event.preventDefault()}
          className="flex w-full flex-col items-center gap-4 rounded-lg border-4 border-border bg-surface p-4"
          style={{ minBlockSize: `${TOUCH_TARGET_PX * 2}px` }}
        >
          <span
            key={beat}
            style={{
              animationName: "sanad-rise",
              animationDuration: "400ms",
              animationFillMode: "both",
            }}
          >
            {showKeyword ? (
              <LetterKeywordArt code={artCode} size={Math.round(cardSize * 1.5)} />
            ) : (
              <SkillArt code={artCode} size={Math.round(cardSize * 1.5)} />
            )}
          </span>
          <span className="text-lg text-ink-muted">{labels.next}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col items-center gap-5">
      <InstructionBubble
        text={activity.instruction_ar}
        replayLabel={labels.replay}
        onReplay={onReplay}
      />
      <ChoiceRow>
        {activity.choices.map((choice) => (
          <ChoiceCard
            key={choice.skill_id}
            id={choice.skill_id}
            imageUrl={choice.image}
            altAr={choice.alt_ar}
            labelAr={choice.label_ar}
            size={cardSize}
            highlight={highlightFor(activity, choice.skill_id, highlight)}
            chosen={chosenId === choice.skill_id}
            onChoose={() => onAnswer(choice.skill_id, choice.correct ? "correct" : "incorrect")}
          />
        ))}
      </ChoiceRow>
    </div>
  );
}
