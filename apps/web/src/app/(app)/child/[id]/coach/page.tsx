import { getTranslations } from "next-intl/server";

import { NextExerciseCard } from "@/components/caregiver/NextExerciseCard";
import { CoachChat } from "@/components/chat/CoachChat";
import { Card } from "@/components/ui/Card";
import { getChatHistory, getChild, getNextExercise, getSpeechCapabilities } from "@/lib/queries";

/**
 * The coach.
 *
 * One page holding the two things the RAG layer produces: what to do next, and
 * an assistant that can answer questions about why. Both read the same
 * retrieval index over this child's history, which is the reason they belong on
 * one screen rather than two — the recommendation is the assistant's answer to
 * a question nobody had to type.
 *
 * An RSC. Everything that can be fetched on the server is, in parallel; the
 * only client component is the chat form, because typing needs state. The
 * access token stays in an httpOnly cookie throughout.
 */

export default async function CoachPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("coach");

  // In parallel: four independent reads, and a failure in any one of them
  // degrades its own card rather than the page. `apiFetchOrNull` is what makes
  // that true without a try/catch per call.
  const [child, recommendation, history, speech] = await Promise.all([
    getChild(id),
    getNextExercise(id),
    getChatHistory(id, "caregiver"),
    getSpeechCapabilities(),
  ]);

  // The server has no TTS provider today, so the browser speaks. Read rather
  // than assumed: turning a server provider on later must not need a client
  // release, which is the whole reason the capability endpoint reports a
  // `client_fallback` instead of a bare boolean.
  const useBrowserSpeech = speech?.tts.supported !== true;
  const previous = history?.messages ?? [];

  return (
    <div data-testid="coach-page" className="space-y-6">
      <h1 className="text-2xl font-semibold text-ink">{t("title")}</h1>

      <NextExerciseCard childId={id} recommendation={recommendation} />

      <CoachChat
        childId={id}
        audioRatePct={child?.audio_rate_pct ?? 85}
        useBrowserSpeech={useBrowserSpeech}
      />

      {previous.length > 0 ? (
        <section data-testid="coach-history">
          <h2 className="mb-3 font-semibold text-ink">{t("history")}</h2>
          <ol className="space-y-3">
            {/* Newest last, the order a transcript is read in. An escalated or
                blocked turn is kept and marked rather than hidden: a caregiver
                scrolling back must not find their question with no answer next
                to it and conclude the app lost it. */}
            {previous.map((message) => (
              <li key={`${message.at}-${message.role}`}>
                <Card
                  className={message.role === "user" ? "bg-primary-soft/30" : ""}
                  data-outcome={message.outcome}
                >
                  <p className="text-ink">{message.text_ar}</p>
                  {message.role === "assistant" && message.outcome !== "ok" ? (
                    <p className="mt-2 text-sm text-ink-muted">{t(`outcome_${message.outcome}`)}</p>
                  ) : null}
                </Card>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
