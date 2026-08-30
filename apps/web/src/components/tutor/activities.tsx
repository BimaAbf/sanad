"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { SkillArt } from "@/components/art/SkillArt";
import { ChoiceCard } from "@/components/child/ChoiceCard";
import { TracingPad, type Stroke } from "@/components/tutor/TracingPad";
import { TOUCH_TARGET_PX } from "@/lib/interaction";
import { listenOnce, speechSupport } from "@/lib/speech";
import type { Activity, ResponsePayload, TutorOption } from "@/lib/tutor";

/**
 * One renderer per activity type, and one contract between them.
 *
 * Every component here takes the same props and calls `onSubmit` with a
 * `ResponsePayload`. None of them knows which answer is right — the server does
 * not send it — so none of them can style a card as wrong, celebrate early, or
 * skip the round trip. That is the architecture, not a rule they are following.
 *
 * They are separate components rather than one configurable screen because the
 * eight ask genuinely different things of a child, and a single component with
 * eight branches is how one of them quietly acquires a failure state.
 */

export interface ActivityProps {
  activity: Activity;
  /** False while a response is in flight, so a second tap cannot start a second. */
  enabled: boolean;
  /** Highlights the target from the second rung of the prompt ladder. */
  hint: boolean;
  onSubmit: (response: ResponsePayload) => void;
  onReplay: () => void;
  labels: {
    replay: string;
    mic: string;
    override: string;
    confirm: string;
    done: string;
  };
}

/** 104px so two cards plus their gaps fit side by side on a 320px phone. */
const CARD_PX = 104;

function Instruction({
  activity,
  onReplay,
  replayLabel,
}: {
  activity: Activity;
  onReplay: () => void;
  replayLabel: string;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-2">
      <div className="flex w-full items-center justify-center gap-3">
        <button
          type="button"
          data-testid="replay"
          aria-label={replayLabel}
          onClick={onReplay}
          className="grid shrink-0 place-items-center rounded-pill bg-accent-soft text-3xl transition-transform duration-fast active:scale-95"
          style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
        >
          🔊
        </button>
        <p data-testid="instruction" className="text-child font-semibold leading-tight text-ink">
          {activity.presentation.instruction_ar}
        </p>
      </div>
      {activity.presentation.demonstration_ar ? (
        // Rendered as part of the instruction rather than as a separate step:
        // the decision said to demonstrate, so the demonstration is the first
        // thing the child sees, not something they have to ask for.
        <p data-testid="demonstration" className="text-lg text-ink-muted">
          {activity.presentation.demonstration_ar}
        </p>
      ) : null}
    </div>
  );
}

function ChoiceGrid({ children }: { children: React.ReactNode }) {
  // Two fixed columns rather than a wrapping flex row. At 320px a flex row puts
  // the second choice on a second line, and two choices that are meant to be
  // compared can only be compared side by side. The >= 20px gap docs/06 §5 asks
  // for is `gap-5` on this container, never a margin on the cards.
  return (
    <div className="mx-auto grid w-full max-w-[520px] grid-cols-2 items-stretch gap-5">
      {children}
    </div>
  );
}

function Choices({
  activity,
  enabled,
  hint,
  onSubmit,
  onReplay,
  labels,
}: ActivityProps) {
  const target = activity.skill_code;
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      {activity.presentation.sample ? (
        // The card being matched against. Not a button: it is the question, and
        // a child who taps the question has not answered it.
        <div
          data-testid="match-sample"
          className="flex flex-col items-center gap-2 rounded-lg border-4 border-dashed border-primary bg-primary-soft p-3"
        >
          <SkillArt code={activity.presentation.sample.skill_code} size={CARD_PX} />
        </div>
      ) : null}
      <ChoiceGrid>
        {activity.presentation.options.map((option) => (
          <ChoiceCard
            key={option.option_id}
            id={option.option_id}
            altAr={option.alt_ar}
            // A listening task with the words written on the cards is a reading
            // task. The server says which this is; the client does not guess.
            labelAr={activity.presentation.hide_labels ? "" : option.label_ar}
            size={CARD_PX}
            // The hint points at the skill being taught, which the client DOES
            // know — it is in `skill_code`. What it does not know is which
            // option is correct for a matching activity, and there the hint is
            // simply not offered rather than guessed at.
            highlight={hint && option.skill_code === target ? "pulse" : "none"}
            onChoose={() =>
              enabled ? onSubmit({ kind: "choice", option_id: option.option_id }) : undefined
            }
          />
        ))}
      </ChoiceGrid>
    </div>
  );
}

/** `num_7` -> 7. The mirror of `build.numeral_value`, which owns the format. */
function numeralValue(skillCode: string): number {
  const suffix = skillCode.split("_")[1] ?? "";
  return /^\d+$/.test(suffix) ? Number(suffix) : 0;
}

function Counting({ activity, enabled, onSubmit, onReplay, labels }: ActivityProps) {
  const count = activity.presentation.object_count;
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      <div
        data-testid="counting-objects"
        aria-label={`${count}`}
        className="mx-auto flex max-w-[420px] flex-wrap items-center justify-center gap-3 rounded-lg bg-primary-soft p-4"
      >
        {Array.from({ length: Math.max(count, 0) }, (_, index) => (
          <SkillArt key={index} code="hh_cup" size={56} />
        ))}
      </div>
      <ChoiceGrid>
        {activity.presentation.options.map((option) => (
          <ChoiceCard
            key={option.option_id}
            id={option.option_id}
            altAr={option.alt_ar}
            labelAr={option.label_ar}
            size={CARD_PX}
            onChoose={() =>
              // A COUNT, not a choice. The child is saying "three", and the
              // card they tapped is how they said it — so the response carries
              // the number rather than the card, and the server compares it
              // with the number of things it put on screen.
              enabled
                ? onSubmit({ kind: "count", value: numeralValue(option.skill_code) })
                : undefined
            }
          />
        ))}
      </ChoiceGrid>
    </div>
  );
}

function Sorting({ activity, enabled, onSubmit, onReplay, labels }: ActivityProps) {
  const [placed, setPlaced] = useState<Record<string, string>>({});
  const [held, setHeld] = useState<TutorOption | null>(null);

  useEffect(() => {
    setPlaced({});
    setHeld(null);
  }, [activity.activity_id]);

  const remaining = activity.presentation.options.filter(
    (option) => !(option.option_id in placed),
  );
  const complete = remaining.length === 0;

  // Tap-a-card then tap-a-bin, not drag-and-drop. Dragging needs a sustained
  // press and a controlled release, which is precisely the motor pattern this
  // population finds hardest; two taps is the same task without it.
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      <div className="flex flex-wrap justify-center gap-4" data-testid="sort-cards">
        {remaining.map((option) => (
          <button
            key={option.option_id}
            type="button"
            aria-pressed={held?.option_id === option.option_id}
            onClick={() => setHeld(option)}
            className={`rounded-lg border-4 p-2 ${
              held?.option_id === option.option_id
                ? "border-primary bg-primary-soft"
                : "border-transparent"
            }`}
            style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
          >
            <SkillArt code={option.skill_code} size={72} />
            <span className="block text-base">{option.label_ar}</span>
          </button>
        ))}
      </div>
      <div className="flex w-full justify-center gap-5" data-testid="sort-bins">
        {activity.presentation.bins.map((bin) => (
          <button
            key={bin.bin_id}
            type="button"
            data-testid={`bin-${bin.bin_id}`}
            onClick={() => {
              if (!held) return;
              setPlaced((current) => ({ ...current, [held.option_id]: bin.bin_id }));
              setHeld(null);
            }}
            className="flex flex-col items-center gap-2 rounded-lg border-4 border-dashed border-accent bg-accent-soft p-4"
            style={{ minInlineSize: "120px", minBlockSize: "120px" }}
          >
            <SkillArt code={bin.art_skill_code} size={56} />
            <span className="text-lg font-semibold">{bin.label_ar}</span>
            <span className="text-base text-ink-muted">
              {Object.values(placed).filter((value) => value === bin.bin_id).length}
            </span>
          </button>
        ))}
      </div>
      <button
        type="button"
        data-testid="sort-submit"
        disabled={!complete || !enabled}
        onClick={() => onSubmit({ kind: "sort", assignments: placed })}
        className="rounded-pill bg-primary px-8 py-4 text-xl text-on-primary disabled:opacity-40"
        style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
      >
        {labels.done}
      </button>
    </div>
  );
}

function Sequencing({ activity, enabled, onSubmit, onReplay, labels }: ActivityProps) {
  const [order, setOrder] = useState<string[]>([]);

  useEffect(() => {
    setOrder([]);
  }, [activity.activity_id]);

  const pool = activity.presentation.options.filter(
    (option) => !order.includes(option.option_id),
  );
  const complete = pool.length === 0;
  const byId = useMemo(
    () => new Map(activity.presentation.options.map((option) => [option.option_id, option])),
    [activity.presentation.options],
  );

  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      <ol
        data-testid="sequence-slots"
        className="flex min-h-[104px] w-full max-w-[520px] items-center justify-center gap-4 rounded-lg border-4 border-dashed border-primary-soft p-3"
      >
        {order.map((id, index) => (
          <li key={id}>
            <button
              type="button"
              aria-label={`${index + 1}`}
              onClick={() => setOrder((current) => current.filter((value) => value !== id))}
              style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
            >
              <SkillArt code={byId.get(id)?.skill_code ?? ""} size={72} />
            </button>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap justify-center gap-4" data-testid="sequence-pool">
        {pool.map((option) => (
          <button
            key={option.option_id}
            type="button"
            onClick={() => setOrder((current) => [...current, option.option_id])}
            style={{ minInlineSize: `${TOUCH_TARGET_PX}px`, minBlockSize: `${TOUCH_TARGET_PX}px` }}
          >
            <SkillArt code={option.skill_code} size={72} />
            <span className="block text-base">{option.label_ar}</span>
          </button>
        ))}
      </div>
      <button
        type="button"
        data-testid="sequence-submit"
        disabled={!complete || !enabled}
        onClick={() => onSubmit({ kind: "sequence", order })}
        className="rounded-pill bg-primary px-8 py-4 text-xl text-on-primary disabled:opacity-40"
        style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
      >
        {labels.done}
      </button>
    </div>
  );
}

function Speaking({ activity, enabled, onSubmit, onReplay, labels }: ActivityProps) {
  const [listening, setListening] = useState(false);
  const cancel = useRef<(() => void) | null>(null);
  const [support, setSupport] = useState({ recognition: false });

  // Feature detection on the client only. A microphone button that does
  // nothing when tapped is worse than an absent one, especially for a caregiver
  // who will conclude the app is broken.
  useEffect(() => {
    setSupport({ recognition: speechSupport().recognition });
    return () => cancel.current?.();
  }, []);

  const listen = () => {
    if (!enabled || listening) return;
    setListening(true);
    const stop = listenOnce({
      onResult: (transcript, confidence) => {
        setListening(false);
        onSubmit({ kind: "speech", transcript, confidence, recogniser_available: true });
      },
      onError: () => {
        setListening(false);
        // A recogniser error is not a wrong answer and never lands as one: the
        // server turns "nothing heard" into `uncertain`, and the caregiver
        // button is already on screen.
        onSubmit({
          kind: "speech",
          transcript: "",
          confidence: 0,
          recogniser_available: true,
        });
      },
      onEnd: () => setListening(false),
    });
    cancel.current = stop;
    if (stop === null) {
      setListening(false);
      onSubmit({
        kind: "speech",
        transcript: "",
        confidence: 0,
        recogniser_available: false,
      });
    }
  };

  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      <SkillArt code={activity.skill_code} size={140} />
      <p className="text-child font-semibold">{activity.presentation.target_word_ar}</p>

      {support.recognition ? (
        <button
          type="button"
          data-testid="mic"
          aria-label={labels.mic}
          aria-pressed={listening}
          disabled={!enabled}
          onClick={listen}
          className={`grid place-items-center rounded-pill text-3xl ${
            listening ? "bg-primary text-on-primary" : "bg-accent-soft"
          } disabled:opacity-40`}
          style={{ minInlineSize: "120px", minBlockSize: "120px" }}
        >
          🎤
        </button>
      ) : (
        <p data-testid="mic-unavailable" className="text-lg text-ink-muted">
          {labels.override}
        </p>
      )}

      {/* Permanently on screen beside every speaking activity, rather than
          appearing after two failed tries — appearing after two failed tries
          would mean there had been two failures. */}
      {activity.presentation.caregiver_confirm_allowed ? (
        <button
          type="button"
          data-testid="caregiver-confirm"
          disabled={!enabled}
          onClick={() =>
            onSubmit({
              kind: "speech",
              transcript: "",
              confidence: 0,
              caregiver_confirmed: true,
            })
          }
          className="rounded-pill border-2 border-primary px-6 py-3 text-lg disabled:opacity-40"
          style={{ minBlockSize: "48px" }}
        >
          {labels.confirm}
        </button>
      ) : null}
    </div>
  );
}

function Tracing({ activity, enabled, onSubmit, onReplay, labels }: ActivityProps) {
  const [captured, setCaptured] = useState<{ strokes: Stroke[]; w: number; h: number }>({
    strokes: [],
    w: 0,
    h: 0,
  });

  return (
    <div className="flex w-full flex-col items-center gap-5">
      <Instruction activity={activity} onReplay={onReplay} replayLabel={labels.replay} />
      <TracingPad
        referencePath={activity.presentation.reference_path}
        glyphAr={activity.presentation.glyph_ar}
        disabled={!enabled}
        onChange={(strokes, w, h) => setCaptured({ strokes, w, h })}
      />
      <button
        type="button"
        data-testid="tracing-submit"
        // Enabled as soon as there is any ink at all. A blank canvas has
        // nothing to submit; a poor attempt is for the server to judge, and
        // refusing to send it here would be the client deciding.
        disabled={!enabled || captured.strokes.length === 0}
        onClick={() =>
          onSubmit({
            kind: "strokes",
            strokes: captured.strokes,
            width: captured.w,
            height: captured.h,
          })
        }
        className="rounded-pill bg-primary px-8 py-4 text-xl text-on-primary disabled:opacity-40"
        style={{ minBlockSize: `${TOUCH_TARGET_PX}px` }}
      >
        {labels.done}
      </button>
    </div>
  );
}

const RENDERERS: Record<string, (props: ActivityProps) => React.ReactElement> = {
  select_picture: Choices,
  listen_choose: Choices,
  match_pair: Choices,
  count_objects: Counting,
  sort_category: Sorting,
  order_sequence: Sequencing,
  speak_word: Speaking,
  trace_letter: Tracing,
};

/**
 * The renderer for one activity.
 *
 * An unknown type renders selection rather than nothing — the server's
 * guardrail already repairs unknown types, so reaching here with one means the
 * two have drifted, and a blank screen is the worst way for a child to find
 * that out.
 */
export function ActivityView(props: ActivityProps) {
  const Renderer = RENDERERS[props.activity.activity_type] ?? Choices;
  return (
    <div data-testid="activity" data-activity-type={props.activity.activity_type}>
      <Renderer {...props} />
    </div>
  );
}
