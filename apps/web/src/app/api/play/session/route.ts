import { NextResponse } from "next/server";

import { skill, spokenLabel } from "@/content/curriculum";
import { ApiError, apiFetch } from "@/lib/api";
import type { ManifestActivity, ManifestChoice, SessionManifest } from "@/lib/manifest";
import { getActiveChildId } from "@/lib/session";

/**
 * The route handler `lib/play-session.ts` has always fetched and nothing has
 * ever answered.
 *
 * `/play` is a client component — it must be, because the prompt ladder is a
 * timer and every choice is a tap — so it cannot call `apiFetch`, which reads
 * the access token from an httpOnly cookie on the server. This is the hop that
 * lets it reach the API without the token ever entering the page.
 *
 * A failure here is not an error the child sees: `loadSession` falls back to
 * the bundled curriculum on any non-2xx, which is docs/01 P5 ("the child is
 * never blocked") implemented rather than asserted. So the status codes below
 * are for the caregiver-facing logs, not for the child.
 */

/** What `POST /play/sessions` returns. Transcribed from `play/schemas.py`. */
interface ApiChoice {
  skill_id: string;
  code: string;
  label_ar: string;
  alt_ar: string;
  correct: boolean;
}

interface ApiActivity {
  activity_code: string;
  skill_id: string;
  skill_code: string;
  instruction_ar: string;
  choices: ApiChoice[];
}

interface ApiSession {
  session_id: string;
  child_id: string;
  plan_source: string;
  wait_time_ms: number;
  max_choices: number;
  calm_mode: boolean;
  activities: ApiActivity[];
}

/**
 * The three rungs, identical for every activity — the same ladder
 * `buildLocalSession` attaches. docs/06 §4 fixes it, and a ladder that varies
 * per activity is one a child has to re-learn each time, which is not a ladder.
 */
const LADDER: ManifestActivity["prompt_ladder"] = [
  { level: "gestural", highlight: "correct" },
  { level: "partial_verbal", highlight: "correct" },
  { level: "full_model", highlight: "correct", auto_select: true },
];

/**
 * `<kind>:<skill code>` — the shape the API builds and `progress/history.py`
 * already produced. An unrecognised kind falls back to `listen_point`, which
 * every skill can be taught with, rather than rendering nothing.
 */
function kindOf(activityCode: string): ManifestActivity["kind"] {
  const prefix = activityCode.split(":")[0];
  switch (prefix) {
    case "match_pair":
    case "say_it":
    case "sort_category":
    case "story_moment":
      return prefix;
    default:
      return "listen_point";
  }
}

/**
 * `skill_id` in the manifest is a curriculum CODE, not the database uuid: it is
 * what `SkillArt` draws from and what `content/curriculum.ts` is keyed by. The
 * uuid is the server's business and the child app has no use for it.
 */
function toChoice(choice: ApiChoice): ManifestChoice {
  return {
    skill_id: choice.code,
    alt_ar: choice.alt_ar,
    label_ar: choice.label_ar,
    correct: choice.correct,
  };
}

function toManifest(session: ApiSession): SessionManifest {
  return {
    session_id: session.session_id,
    child: {
      wait_time_ms: session.wait_time_ms,
      max_choices: session.max_choices,
      // Not on the API's response yet; the bundled default is the documented
      // one and the child app reads it for the rate Nour speaks at.
      audio_rate_pct: 85,
      calm_mode: session.calm_mode,
    },
    activities: session.activities.map((activity, index) => {
      const known = skill(activity.skill_code);
      return {
        id: `${session.session_id}-${index + 1}-${activity.skill_code}`,
        kind: kindOf(activity.activity_code),
        skill_id: activity.skill_code,
        instruction_ar: activity.instruction_ar,
        // What Nour says out loud: the colloquial word, not the glyph. The
        // bundle knows it for a skill it has; otherwise the label is the best
        // available answer and is still a word.
        spoken_ar: known ? spokenLabel(known) : (activity.choices[0]?.label_ar ?? ""),
        choices: activity.choices.map(toChoice),
        prompt_ladder: LADDER,
      };
    }),
    local: false,
  };
}

export async function POST(request: Request): Promise<NextResponse> {
  let body: { minutes?: number } = {};
  try {
    body = (await request.json()) as { minutes?: number };
  } catch {
    body = {};
  }

  // The child app does not know which child it is running for, and it should
  // not: that is the caregiver's session, in an httpOnly cookie. The API
  // re-checks access on it regardless, which is where it must be checked.
  const childId = await getActiveChildId();
  if (!childId) {
    return NextResponse.json({ detail: "No active child." }, { status: 409 });
  }

  try {
    const session = await apiFetch<ApiSession>("/play/sessions", {
      method: "POST",
      body: {
        child_id: childId,
        ...(body.minutes === undefined ? {} : { minutes: body.minutes }),
      },
    });
    return NextResponse.json(toManifest(session));
  } catch (error) {
    if (error instanceof ApiError) {
      // `status: 0` is `apiFetch`'s "the request never arrived". Reported as
      // 503 rather than passed through, because 0 is not an HTTP status and the
      // outbox switches on the number.
      const status = error.status === 0 ? 503 : error.status;
      return NextResponse.json({ code: error.code, message_ar: error.messageAr }, { status });
    }
    return NextResponse.json({ code: "network_unavailable" }, { status: 503 });
  }
}
