import { getTranslations } from "next-intl/server";

import { selectChildAction } from "@/app/(app)/children/actions";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LinkButton } from "@/components/ui/LinkButton";
import { getMe, getRewards, getStartingAssessment } from "@/lib/queries";

/**
 * The child picker, and the one screen that shows two children are different.
 *
 * Every number here is read from the API — stars from `reward_events`, the
 * starting bands from the child's own assessment — so two children on this page
 * differ because their records differ. Nothing is derived from a name.
 *
 * A child with no starting assessment gets a different call to action from one
 * who has finished it: the assessment is what gives the tutor loop somewhere to
 * start, and a session before it would begin every child in the same place.
 */
export default async function ChildrenPage() {
  const t = await getTranslations("children");
  const ts = await getTranslations("starting");
  const me = await getMe();

  if (!me) {
    return (
      <EmptyState
        title={t("title")}
        body={t("signedOut")}
        action={<LinkButton href="/onboarding">{t("signIn")}</LinkButton>}
      />
    );
  }

  const children = me.children ?? [];
  if (children.length === 0) {
    return (
      <EmptyState
        title={t("title")}
        body={t("emptyBody")}
        action={<LinkButton href="/onboarding">{t("add")}</LinkButton>}
      />
    );
  }

  // In parallel: three children is three pairs of independent reads, and
  // serialising them would put six round trips in front of the first screen a
  // caregiver sees after signing in.
  const profiles = await Promise.all(
    children.map(async (child) => ({
      child,
      rewards: await getRewards(child.id),
      starting: await getStartingAssessment(child.id),
    })),
  );

  return (
    <div dir="rtl" data-testid="children-page">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
          <p className="mt-1 text-ink-muted">{t("subtitle")}</p>
        </div>
        <LinkButton href="/onboarding">{t("add")}</LinkButton>
      </div>

      <ul className="grid gap-4 sm:grid-cols-2">
        {profiles.map(({ child, rewards, starting }) => {
          const assessed = starting?.status === "completed";
          return (
            <li key={child.id} data-testid="child-card" data-child-id={child.id}>
              <Card>
                <h2 className="text-xl font-semibold" data-testid="child-name">
                  {child.display_name}
                </h2>

                <p className="mt-2 text-lg" data-testid={`stars-${child.id}`}>
                  ⭐ {rewards?.stars ?? 0}
                </p>
                {rewards && rewards.achievements.length > 0 ? (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {rewards.achievements.map((achievement) => (
                      <li
                        key={achievement.code}
                        className="rounded-pill bg-accent-soft px-3 py-1 text-base"
                      >
                        🏅 {achievement.label_ar}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {assessed ? (
                  <ul
                    className="mt-4 flex flex-wrap gap-2"
                    data-testid={`bands-${child.id}`}
                  >
                    {Object.entries(starting.area_levels)
                      .slice(0, 6)
                      .map(([area, band]) => (
                        <li
                          key={area}
                          className="rounded-md bg-primary-soft px-3 py-1 text-base"
                        >
                          {area} · {ts(`band.${band}`)}
                        </li>
                      ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-ink-muted">{ts("lede")}</p>
                )}

                <div className="mt-5 flex flex-wrap gap-3">
                  {assessed ? (
                    // The active-child cookie is what `/play` reads, so
                    // choosing a child is a write and goes through an action.
                    <form action={selectChildAction}>
                      <input type="hidden" name="child_id" value={child.id} />
                      <button
                        type="submit"
                        data-testid={`play-${child.id}`}
                        className="rounded-pill bg-primary px-6 py-3 text-on-primary"
                        style={{ minBlockSize: "48px" }}
                      >
                        {ts("startPlaying")}
                      </button>
                    </form>
                  ) : (
                    <LinkButton href={`/child/${child.id}/start`}>{ts("title")}</LinkButton>
                  )}
                  <LinkButton href={`/child/${child.id}/report`} variant="secondary">
                    {t("open")}
                  </LinkButton>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
