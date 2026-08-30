"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The tracing surface. A real canvas, real pointer events, real strokes.
 *
 * What this component does NOT do is decide anything. It captures where the
 * child's finger went and hands the raw strokes up; the score, the threshold
 * and the verdict are computed by `tutor/domain/drawing.py` from those numbers.
 * There is no "looks close enough" here, because a client that could decide
 * that could also decide the other way.
 *
 * Four things it does that matter for this population:
 *
 * * **The guide is drawn under the child's line, always visible.** Tracing is
 *   not recall; hiding the guide would turn it into a writing test.
 * * **Pointer events, not touch or mouse.** One code path for a finger, a
 *   stylus and a mouse, and `setPointerCapture` so a finger that slides off the
 *   canvas edge mid-stroke does not end the stroke somewhere random.
 * * **`touch-action: none`.** Without it the browser scrolls the page instead
 *   of drawing, which on a phone means the child cannot trace at all.
 * * **Undo, not erase-everything.** A child who has drawn three quarters of a
 *   letter and slipped needs the slip removed, not the letter.
 *
 * Coordinates are reported in CSS pixels of the canvas, alongside the canvas
 * size, and the server divides by the longer side. That is what makes a 320 px
 * phone and a 1024 px tablet produce the same score.
 */

export type Stroke = number[][];

const GUIDE_WIDTH = 18;
const INK_WIDTH = 12;

export function TracingPad({
  referencePath,
  glyphAr,
  size = 300,
  disabled = false,
  onChange,
}: {
  /** Strokes of unit-box points, y down — exactly as the server stores them. */
  referencePath: number[][][];
  glyphAr: string;
  size?: number;
  disabled?: boolean;
  onChange: (strokes: Stroke[], width: number, height: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const drawing = useRef<Stroke | null>(null);

  const redraw = useCallback(
    (current: Stroke[]) => {
      const element = canvas.current;
      const context = element?.getContext("2d");
      if (!element || !context) return;

      const ratio = window.devicePixelRatio || 1;
      // Backing store at device resolution, drawing coordinates in CSS pixels.
      // Without this a stroke on a 3x phone is drawn at a third of its width
      // and the guide looks like a hairline.
      if (element.width !== size * ratio) {
        element.width = size * ratio;
        element.height = size * ratio;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, size, size);

      context.lineCap = "round";
      context.lineJoin = "round";

      // The guide, underneath. A dashed grey line rather than a solid one, so
      // the child's own ink is always the more visible of the two.
      context.strokeStyle = "rgba(43, 43, 43, 0.22)";
      context.lineWidth = GUIDE_WIDTH;
      context.setLineDash([14, 10]);
      for (const stroke of referencePath) {
        if (stroke.length < 2) continue;
        context.beginPath();
        stroke.forEach(([x, y], index) => {
          const px = (x ?? 0) * size;
          const py = (y ?? 0) * size;
          if (index === 0) context.moveTo(px, py);
          else context.lineTo(px, py);
        });
        context.stroke();
      }

      context.setLineDash([]);
      context.strokeStyle = "var(--c-primary, #1F7A6C)";
      context.lineWidth = INK_WIDTH;
      for (const stroke of current) {
        if (stroke.length === 0) continue;
        context.beginPath();
        stroke.forEach(([x, y], index) => {
          if (index === 0) context.moveTo(x ?? 0, y ?? 0);
          else context.lineTo(x ?? 0, y ?? 0);
        });
        if (stroke.length === 1) {
          // A single tap still leaves a mark. It will not pass — a dot is not a
          // letter, and the scorer says so — but a child who touched the screen
          // must see that something happened.
          const [x, y] = stroke[0] as [number, number];
          context.lineTo(x + 0.01, y);
        }
        context.stroke();
      }
    },
    [referencePath, size],
  );

  useEffect(() => {
    redraw(strokes);
  }, [redraw, strokes]);

  // A new activity means a clean pad. Keyed on the reference so two tracing
  // activities in a row do not inherit each other's ink.
  useEffect(() => {
    setStrokes([]);
    drawing.current = null;
    onChange([], size, size);
    // Keyed on the reference path, not on `onChange`: the callback is rebuilt
    // on every render of the parent, and depending on it would clear the pad
    // under the child's finger on every state change.
  }, [referencePath, size]);

  const pointFrom = (event: React.PointerEvent<HTMLCanvasElement>): [number, number] => {
    const box = event.currentTarget.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  };

  const start = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawing.current = [pointFrom(event)];
    setStrokes((current) => [...current, drawing.current as Stroke]);
  };

  const move = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled || !drawing.current) return;
    drawing.current.push(pointFrom(event));
    setStrokes((current) => [...current.slice(0, -1), [...(drawing.current as Stroke)]]);
  };

  const finish = () => {
    if (!drawing.current) return;
    drawing.current = null;
    setStrokes((current) => {
      onChange(current, size, size);
      return current;
    });
  };

  const undo = () => {
    setStrokes((current) => {
      const next = current.slice(0, -1);
      onChange(next, size, size);
      return next;
    });
  };

  const clear = () => {
    setStrokes(() => {
      onChange([], size, size);
      return [];
    });
  };

  return (
    <div className="flex flex-col items-center gap-3">
      <canvas
        ref={canvas}
        data-testid="tracing-pad"
        role="img"
        aria-label={`اكتب ${glyphAr}`}
        style={{
          inlineSize: `${size}px`,
          blockSize: `${size}px`,
          // Without this the browser scrolls the page instead of drawing, and
          // on a phone the child cannot trace at all.
          touchAction: "none",
        }}
        className="rounded-lg border-4 border-primary-soft bg-surface"
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={finish}
        onPointerCancel={finish}
        onPointerLeave={finish}
      />
      <div className="flex gap-3">
        <button
          type="button"
          data-testid="tracing-undo"
          onClick={undo}
          disabled={strokes.length === 0}
          className="rounded-pill bg-accent-soft px-5 py-3 text-lg disabled:opacity-40"
          style={{ minBlockSize: "48px" }}
        >
          تراجع
        </button>
        <button
          type="button"
          data-testid="tracing-clear"
          onClick={clear}
          disabled={strokes.length === 0}
          className="rounded-pill bg-accent-soft px-5 py-3 text-lg disabled:opacity-40"
          style={{ minBlockSize: "48px" }}
        >
          من الأول
        </button>
      </div>
    </div>
  );
}
