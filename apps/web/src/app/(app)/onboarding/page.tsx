import { OnboardingFlow } from "@/components/caregiver/OnboardingFlow";
import { isSignedIn } from "@/lib/session";

/**
 * Sign up, or add another child.
 *
 * A server component around the client flow, for one reason: whether a
 * caregiver is signed in is a fact about an httpOnly cookie, which the flow
 * cannot read. Without it, a caregiver adding a second child was sent back to
 * the phone screen and asked to verify a code they did not need — and the OTP
 * is rate limited at three an hour, so the second child could simply be
 * refused.
 */
export default async function OnboardingPage() {
  return <OnboardingFlow signedIn={await isSignedIn()} />;
}
