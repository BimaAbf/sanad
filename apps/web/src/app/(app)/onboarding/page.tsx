"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";

/**
 * Onboarding: phone → OTP → caregiver → child → consent → first assessment.
 *
 * One decision per screen (docs/06 §3). The consent step is the one that
 * matters legally and the one most likely to be rushed, so it is its own step
 * with each toggle stated in full rather than a single "I agree to everything"
 * checkbox — three of the seven are mandatory and the other four must be
 * genuinely refusable.
 */

type Step = "phone" | "otp" | "caregiver" | "child" | "consent" | "done";

const STEPS: Step[] = ["phone", "otp", "caregiver", "child", "consent", "done"];

const CONSENT_KEYS = [
  { key: "data_processing", mandatory: true },
  { key: "ai_processing", mandatory: true },
  { key: "terms_not_medical", mandatory: true },
  { key: "voice_asr", mandatory: false },
  { key: "voice_retention", mandatory: false },
  { key: "clinician_share", mandatory: false },
  { key: "research_aggregate", mandatory: false },
] as const;

export default function OnboardingPage() {
  const t = useTranslations("onboarding");
  const tc = useTranslations("consent");
  const [step, setStep] = useState<Step>("phone");
  const [granted, setGranted] = useState<Record<string, boolean>>({});

  const advance = () => setStep(STEPS[Math.min(STEPS.indexOf(step) + 1, STEPS.length - 1)]!);
  const mandatoryMet = CONSENT_KEYS.filter((c) => c.mandatory).every((c) => granted[c.key]);

  return (
    <div data-testid="onboarding" data-step={step}>
      <Card>
        {step === "phone" ? (
          <>
            <h1 className="mb-4 text-2xl font-semibold">{t("phoneTitle")}</h1>
            <Field id="phone" label={t("phoneLabel")} help={t("phoneHelp")} type="tel" inputMode="tel" />
            <Button onClick={advance} data-testid="phone-submit">
              {t("phoneSubmit")}
            </Button>
          </>
        ) : null}

        {step === "otp" ? (
          <>
            <h1 className="mb-4 text-2xl font-semibold">{t("otpTitle")}</h1>
            <Field
              id="otp"
              label={t("otpTitle")}
              help={t("otpHelp")}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
            />
            <Button onClick={advance} data-testid="otp-submit">
              {t("otpTitle")}
            </Button>
          </>
        ) : null}

        {step === "caregiver" ? (
          <>
            <h1 className="mb-4 text-2xl font-semibold">{t("profileTitle")}</h1>
            <Field id="caregiver-name" label={t("profileName")} />
            <Button onClick={advance} data-testid="caregiver-submit">
              {t("profileTitle")}
            </Button>
          </>
        ) : null}

        {step === "child" ? (
          <>
            <h1 className="mb-4 text-2xl font-semibold">{t("childTitle")}</h1>
            <Field id="child-name" label={t("childName")} />
            <Field id="child-dob" label={t("childDob")} type="date" />
            <Field id="child-gest" label={t("childGestational")} type="number" min={22} max={45} />
            <Button onClick={advance} data-testid="child-submit">
              {t("childTitle")}
            </Button>
          </>
        ) : null}

        {step === "consent" ? (
          <>
            <h1 className="mb-4 text-2xl font-semibold">{t("consentTitle")}</h1>
            <p className="mb-5 text-ink-muted">{t("consentIntro")}</p>
            <ul className="space-y-4">
              {CONSENT_KEYS.map((consent) => (
                <li key={consent.key} className="flex items-start gap-3">
                  <input
                    id={`consent-${consent.key}`}
                    type="checkbox"
                    data-testid={`consent-${consent.key}`}
                    checked={granted[consent.key] ?? false}
                    onChange={(event) =>
                      setGranted((value) => ({ ...value, [consent.key]: event.target.checked }))
                    }
                  />
                  <label htmlFor={`consent-${consent.key}`}>
                    <span className="font-semibold">{consent.key}</span>{" "}
                    <span className="text-sm text-ink-muted">
                      {consent.mandatory ? tc("mandatory") : tc("optional")}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <Button
              className="mt-6"
              disabled={!mandatoryMet}
              onClick={advance}
              data-testid="consent-submit"
            >
              {t("firstAssessment")}
            </Button>
          </>
        ) : null}

        {step === "done" ? <p data-testid="onboarding-done">{t("firstAssessment")}</p> : null}
      </Card>
    </div>
  );
}
