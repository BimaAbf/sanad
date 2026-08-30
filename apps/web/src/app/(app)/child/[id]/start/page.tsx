import { StartingAssessment } from "@/components/caregiver/StartingAssessment";

/**
 * The starting-assessment runner.
 *
 * A thin server component around a client one: the runner has to respond to a
 * tap without a page load, and the child id is the only thing it needs from the
 * server. Authorisation is not this page's job — every call the runner makes
 * goes through `/api/starting`, which attaches the caregiver's token, and the
 * API refuses a child that is not theirs.
 */
export default async function StartingAssessmentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <StartingAssessment childId={id} />;
}
