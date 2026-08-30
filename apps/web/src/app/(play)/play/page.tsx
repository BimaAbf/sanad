import { getTranslations } from "next-intl/server";

import { PlaySession } from "@/components/tutor/PlaySession";
import { EmptyState } from "@/components/ui/EmptyState";
import { LinkButton } from "@/components/ui/LinkButton";
import { DEFAULT_PROFILE, type AccessibilityProfile } from "@/lib/interaction";
import { getChild } from "@/lib/queries";
import { getActiveChildId, isSignedIn } from "@/lib/session";

/**
 * The child's screen.
 *
 * A server component that does exactly two things — resolve which child this
 * is, and read their accessibility settings — and then hands both to the
 * client session. The session itself is entirely server-driven: every activity
 * is a teaching decision taken by the API after the previous answer was
 * recorded, and there is no local fallback.
 *
 * That last point is the change from the previous version worth stating. The
 * old screen built a session from a bundled curriculum whenever the API was
 * slow to answer, which meant the child could play for ten minutes against
 * nothing and every tap was discarded — indistinguishable, on screen, from a
 * working product. A child with no session now sees a start button that does
 * not work rather than a session that does not count.
 */
export default async function PlayPage() {
  const t = await getTranslations("play");
  const tLanding = await getTranslations("landing");

  if (!(await isSignedIn())) {
    return (
      <EmptyState
        title={t("title")}
        body={tLanding("lede")}
        action={<LinkButton href="/onboarding">{tLanding("start")}</LinkButton>}
      />
    );
  }

  const childId = await getActiveChildId();
  if (!childId) {
    return (
      <EmptyState
        title={t("title")}
        body={t("noChild")}
        action={<LinkButton href="/children">{t("start")}</LinkButton>}
      />
    );
  }

  // Null is the documented "not configured" / "no access" case. The defaults
  // are the conservative ones — the longest wait and the fewest choices — so a
  // child whose record could not be read is given the easier session rather
  // than the harder one.
  const child = await getChild(childId);
  const profile: AccessibilityProfile = child
    ? {
        waitTimeMs: child.wait_time_ms,
        maxChoices: child.max_choices,
        audioRatePct: child.audio_rate_pct,
        calmMode: child.calm_mode,
      }
    : DEFAULT_PROFILE;

  return <PlaySession childId={childId} profile={profile} />;
}
