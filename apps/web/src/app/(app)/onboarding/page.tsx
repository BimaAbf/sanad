"use client";

import { useTranslations } from "next-intl";
import { useActionState, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { EMPTY_STATE } from "@/lib/action-state";
import { createChildAction, requestOtpAction, verifyOtpAction } from "./actions";

/**
 * Onboarding: phone → OTP → child → consent → first assessment.
 *
 * One decision per screen (docs/06 §3). The consent step is the one that
 * matters legally and the one most likely to be rushed, so it is its own step
 * with each toggle stated in full rather than a single "I agree to everything"
 * checkbox — three of the seven are mandatory and the other four must be
 * genuinely refusable.
 *
 * Every step posts to a server action. These buttons used to advance a local
 * `useState` and call nothing at all, which is why an account was never
 * created: the flow reached "done" without a single request having been made.
 *
 * The child and consent steps share ONE form. The API takes the child and its
 * consents in a single `POST /children` — the consent gate refuses a child
 * whose mandatory consents are absent — so posting them separately would mean
 * a request designed to fail. The steps stay visually separate; the non-current
 * fieldset is hidden rather than unmounted, so its values still post.
 */

type Step = "phone" | "otp" | "child" | "consent";

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
  const tApp = useTranslations("app");
  const tc = useTranslations("consent");
  const te = useTranslations("errors");

  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [granted, setGranted] = useState<Record<string, boolean>>({});

  const [otpState, sendOtp, sendingOtp] = useActionState(requestOtpAction, EMPTY_STATE);
  const [verifyState, verify, verifying] = useActionState(verifyOtpAction, EMPTY_STATE);
  const [childState, createChild, creating] = useActionState(createChildAction, EMPTY_STATE);

  // Advancing is driven by the action's result, not by the click. A code the
  // API rejected must not move the caregiver forward.
  useEffect(() => {
    if (otpState.ok) setStep("otp");
  }, [otpState]);
  useEffect(() => {
    if (verifyState.ok) setStep("child");
  }, [verifyState]);

  const mandatoryMet = CONSENT_KEYS.filter((c) => c.mandatory).every((c) => granted[c.key]);
  const error = otpState.error ?? verifyState.error ?? childState.error;

  return (
    <div data-testid="onboarding" data-step={step}>
      <Card>
        {error ? (
          <p role="alert" className="mb-5 rounded-md border border-attention p-4 text-attention">
            {error}
          </p>
        ) : null}

        {step === "phone" ? (
          <form action={sendOtp}>
            <h1 className="mb-4 text-2xl font-semibold">{t("phoneTitle")}</h1>
            <Field
              id="phone"
              name="phone"
              label={t("phoneLabel")}
              help={t("phoneHelp")}
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              required
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
            <Button type="submit" disabled={sendingOtp} data-testid="phone-submit">
              {t("phoneSubmit")}
            </Button>
          </form>
        ) : null}

        {step === "otp" ? (
          <form action={verify}>
            <h1 className="mb-4 text-2xl font-semibold">{t("otpTitle")}</h1>
            <input type="hidden" name="phone" value={phone} />
            <Field
              id="otp"
              name="code"
              label={t("otpTitle")}
              help={t("otpHelp")}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              required
            />
            <Button type="submit" disabled={verifying} data-testid="otp-submit">
              {t("otpTitle")}
            </Button>
          </form>
        ) : null}

        {step === "child" || step === "consent" ? (
          <form action={createChild}>
            <fieldset hidden={step !== "child"}>
              <h1 className="mb-4 text-2xl font-semibold">{t("childTitle")}</h1>
              <Field id="child-name" name="display_name" label={t("childName")} required />
              <Field
                id="child-dob"
                name="date_of_birth"
                label={t("childDob")}
                type="date"
                required
              />
              <Field
                id="child-gest"
                name="gestational_weeks"
                label={t("childGestational")}
                type="number"
                min={22}
                max={45}
              />
              <Button type="button" onClick={() => setStep("consent")} data-testid="child-submit">
                {tApp("next")}
              </Button>
            </fieldset>

            <fieldset hidden={step !== "consent"}>
              <h1 className="mb-4 text-2xl font-semibold">{t("consentTitle")}</h1>
              <p className="mb-5 text-ink-muted">{t("consentIntro")}</p>
              <ul className="space-y-4">
                {CONSENT_KEYS.map((consent) => (
                  <li key={consent.key} className="flex items-start gap-3">
                    <input
                      id={`consent-${consent.key}`}
                      name="consents"
                      value={consent.key}
                      type="checkbox"
                      className="mt-1 size-5"
                      data-testid={`consent-${consent.key}`}
                      checked={granted[consent.key] ?? false}
                      onChange={(event) =>
                        setGranted((value) => ({
                          ...value,
                          [consent.key]: event.target.checked,
                        }))
                      }
                    />
                    <label htmlFor={`consent-${consent.key}`}>
                      {/* The Arabic here is the same string the database holds:
                          it is generated into the message catalogue from
                          migration 0003, so the wording a caregiver agrees to
                          and the wording recorded in the ledger cannot drift. */}
                      <span>{tc(`labels.${consent.key}`)}</span>{" "}
                      <span className="text-sm text-ink-muted">
                        {consent.mandatory ? tc("mandatory") : tc("optional")}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="mt-6 flex gap-3">
                <Button type="button" variant="ghost" onClick={() => setStep("child")}>
                  {tApp("back")}
                </Button>
                <Button
                  type="submit"
                  disabled={!mandatoryMet || creating}
                  data-testid="consent-submit"
                >
                  {t("firstAssessment")}
                </Button>
              </div>
              {!mandatoryMet ? (
                <p className="mt-3 text-sm text-ink-muted">{te("consentRequired")}</p>
              ) : null}
            </fieldset>
          </form>
        ) : null}
      </Card>
    </div>
  );
}
