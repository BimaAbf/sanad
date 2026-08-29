# 06 — Frontend, UX & Accessibility

Two very different users share one codebase: an anxious adult reading dense information on a phone, and a child with Down syndrome who needs the interface to be slow, large, predictable and kind. They get different design systems built from the same tokens.

---

## 1. Arabic-first, not Arabic-translated

| Concern | Rule |
|---|---|
| Direction | `dir="rtl"` on `<html>`. LTR is the exception, applied per-element for code, phone numbers and URLs with `dir="ltr"` + `unicode-bidi: isolate`. |
| CSS | **Logical properties only.** `margin-inline-start`, `padding-block`, `inset-inline-end`. A stylelint rule bans `margin-left`, `padding-right`, `left`, `right` and fails the build. |
| Icons | Directional icons (arrows, chevrons, back) are mirrored via `[dir="rtl"] .icon-directional { transform: scaleX(-1) }`. Non-directional icons (clock, play) are never mirrored. |
| Numerals | **Eastern Arabic (٠١٢٣٤٥٦٧٨٩)** for anything a child sees and for dates and counts in the caregiver app. Western digits for phone numbers, OTP entry and IDs. `Intl.NumberFormat('ar-EG-u-nu-arab')`. |
| Dates | `Intl.DateTimeFormat('ar-EG')`, Gregorian calendar, Africa/Cairo. |
| Typography | Arabic needs **more leading and larger optical size** than Latin at the same nominal size. Base 17 px, `line-height: 1.9`. Never below 16 px anywhere. |
| Fonts | **IBM Plex Sans Arabic** (open licence, excellent Egyptian legibility, real weight range) with `Noto Sans Arabic` fallback. Self-hosted, subset to Arabic + Arabic-Indic digits + Latin basic, ~44 KB woff2, `font-display: swap`. |
| Copy | Written in Egyptian colloquial for warmth, MSA where precision matters. Every string reviewed by a native speaker before merge. **No machine-translated strings ship.** |
| Pluralisation | Arabic has six plural forms. `next-intl` ICU plurals with all of `zero`, `one`, `two`, `few`, `many`, `other` — a missing form is a lint error. |

---

## 2. Design tokens

```css
:root {
  /* Brand — warm, calm, unmistakably not clinical.
     Every foreground/background pair below meets ≥ 7:1 (WCAG AAA). */
  --c-primary:        #1F6F5C;   /* deep teal — trust without coldness */
  --c-primary-soft:   #E4F2EE;
  --c-accent:         #E8873A;   /* warm amber — actions, celebration */
  --c-accent-soft:    #FDF0E4;
  --c-ink:            #16211E;   /* body text — 14.8:1 on --c-surface */
  --c-ink-muted:      #4A5A55;   /* 7.4:1 */
  --c-surface:        #FFFFFF;
  --c-surface-alt:    #F7F9F8;
  --c-border:         #D6E0DC;

  /* Semantic — deliberately NOT red/green.
     Red reads as failure; this product has no failure states. */
  --c-growing:        #2E7D6B;   /* progress, mastery */
  --c-practising:     #C77E1F;   /* in progress — amber, not warning */
  --c-resting:        #7A8B86;   /* not started — neutral grey, never grey-as-bad */
  --c-attention:      #8B4A6B;   /* plum — needs a look; never alarming red */

  /* Child palette — saturated but not fluorescent, tested for the
     colour-vision differences that co-occur with Down syndrome. */
  --k-red:    #D93A2B;  --k-blue:   #1C6BBF;  --k-yellow: #F0B429;
  --k-green:  #2E8B4A;  --k-purple: #7B4FA8;  --k-orange: #E87722;
  --k-pink:   #D9538C;  --k-brown:  #8B5E3C;  --k-black:  #2B2B2B;
  --k-white:  #FFFFFF;

  /* Type scale — Arabic-tuned */
  --t-xs: 14px; --t-sm: 15px; --t-base: 17px; --t-lg: 20px;
  --t-xl: 24px; --t-2xl: 30px; --t-3xl: 38px; --t-child: 32px;
  --lh-tight: 1.5; --lh-base: 1.9; --lh-loose: 2.1;

  /* Space — 4 px base, generous by default */
  --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px;
  --s-5: 24px; --s-6: 32px; --s-7: 48px; --s-8: 64px;

  /* Radius & elevation — soft, never sharp */
  --r-sm: 8px; --r-md: 14px; --r-lg: 22px; --r-pill: 999px;
  --e-1: 0 1px 2px rgb(22 33 30 / .06);
  --e-2: 0 4px 12px rgb(22 33 30 / .08);

  /* Motion */
  --m-fast: 120ms; --m-base: 220ms; --m-slow: 400ms;
  --m-ease: cubic-bezier(.2,.7,.3,1);

  /* Touch */
  --touch-min: 48px;        /* caregiver app */
  --touch-child: 88px;      /* child app — exceeds the 80 px requirement */
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important;
                           transition-duration: .01ms !important; }
}
```

**Calm mode** (`children.calm_mode = true`) overrides the child palette to desaturated equivalents, disables all sound effects, removes confetti and background patterns, and lengthens inter-activity pauses to 1,200 ms. It is offered during onboarding with the plain question *"طفلك بيتضايق من الأصوات والألوان القوية؟"* rather than buried in settings.

**No dark mode in the child app.** Consistency and predictability beat preference here, and inverted contrast on illustrated content is worse, not better. The caregiver app supports dark mode fully.

---

## 3. Caregiver app patterns

| Pattern | Rule |
|---|---|
| One decision per screen | Especially in onboarding and the assessment runner |
| Progressive disclosure | DQ, norms, and clinical detail live behind explicit expanders |
| Skeletons, never spinners | A spinner on a slow connection reads as broken |
| Optimistic UI on writes | With a visible, undoable rollback on failure |
| Empty states are instructional | "Run your first check-in to see the journey" + the button |
| Errors say what to do next | Never a status code, never "something went wrong" |
| Destructive actions | Two-step, with the consequence named in plain Arabic |
| Forms | Labels above fields (Arabic labels are long), inline validation on blur, never on keystroke |

### Copy guidelines (binding — enforced in review)

**Never write:** "delay", "deficit", "behind", "normal children", "problem", "failed", "score", "IQ", "should be able to", "أطفال طبيعيين", "متأخر".

**Write instead:** "بيتعلم دلوقتي", "الخطوة الجاية", "نراجع مع بعض", "حاجات {{CHILD}} بيعرفها", "تقدّم".

Every user-facing string passes a lint rule with a banned-terms list. Adding a term to the allow-list requires a reviewer from the clinical partner.

---

## 4. Child app patterns

Restating the interaction contract from [04e](04e-components-safety-clients.md) because it is the product:

- Touch targets ≥ 88 px with ≥ 20 px gaps.
- 2 choices by default; 3–4 only for skills already at `practising` or better.
- Instructions ≤ 5 words, spoken and written and illustrated.
- 8-second default wait; no visible timer, ever.
- The prompt ladder guarantees success. **There is no failure state in the product.**
- Animation ≤ 3 Hz and ≤ 400 ms; `prefers-reduced-motion` honoured.
- One voice, one rate, identical repetition of the same instruction.
- 800 ms of calm between activities.
- Progress shown as dots, never numbers or percentages.
- Celebration is proportionate: a brief character animation and one warm phrase. Confetti and fanfare become noise within a week and add cognitive load.

### The prompt ladder in UI terms

```
t=0        "وريني الأحمر"  (audio + text + speaker icon)
t=8s       identical audio repeats, correct card pulses gently at 1.5 Hz
t=16s      "وريني الأح…"   correct card pulses, slight scale-up
t=24s      "الأحمر… ده الأحمر"  correct card lifts, glows, auto-selects after 1.5 s
           → child taps it → full celebration
```

The child experiences four successes in a row over 25 seconds. The database records one `full_model` attempt contributing almost nothing to BKT. Honest measurement, kind presentation.

---

## 5. Accessibility requirements

| Requirement | Target | Verified by |
|---|---|---|
| WCAG 2.2 | AA for `/app` and `/console`; AA + the stricter rules below for `/play` | `axe-core` in Playwright, every route, every CI run |
| Contrast | ≥ 4.5:1 caregiver, **≥ 7:1 child** | Automated token-pair test + per-screen check |
| Touch targets | ≥ 48 px caregiver, **≥ 88 px child** | Playwright bounding-box assertion at 320 px width |
| Keyboard | Full operation of `/app` and `/console`; visible focus ring ≥ 3 px | Manual + automated tab-order test |
| Screen readers | NVDA + TalkBack in Arabic; every image has meaningful Arabic alt text (mandatory DB column) | Manual pass per release |
| Motion | No animation > 3 Hz anywhere | Frame-analysis test on the child app |
| Timing | No time limits anywhere in the product | Code review + explicit test |
| Language | `lang="ar-EG"` on `<html>`; `lang` switched per element for mixed content | Automated |
| Zoom | 200% text zoom without horizontal scroll or clipping | Playwright at 200% |

**Beyond automated checks:** a manual accessibility review with an occupational therapist and two families before the pilot, and again before GA. `axe-core` cannot tell you that an 8-second wait is too short for a particular child. A parent can.

---

## 6. Performance budgets (CI-enforced, hard fail)

| Metric | Caregiver app | Child app |
|---|---|---|
| JS transferred (route) | ≤ 180 KB gz | ≤ 220 KB gz |
| LCP (Moto G4, 4G) | ≤ 1.8 s | ≤ 2.2 s |
| INP | ≤ 200 ms | ≤ 150 ms |
| CLS | ≤ 0.05 | ≤ 0.01 |
| Session manifest + assets | — | ≤ 4 MB, fully preloaded before the first prompt |
| Fonts | ≤ 44 KB woff2, subset | same |

Lighthouse CI runs on every PR with these as failure thresholds, not warnings.

---

## 7. PWA & offline

- `next-pwa` with Workbox. App shell and fonts precached. Skills/media cached stale-while-revalidate.
- Session manifests use cache-first with explicit preloading — the child app never starts a session it cannot finish offline.
- IndexedDB outbox for attempts and events, with Background Sync where available and a foreground drain on `online` otherwise.
- Install prompt shown after the *second* successful play session, never on the first visit.
- An offline banner appears in the caregiver app only; the child app never shows a network state, because the child cannot act on it.

---

## 8. Component inventory

**Shared:** `Button` (primary/secondary/ghost/danger), `Card`, `Sheet`, `Dialog`, `Field`, `OtpInput`, `Toast`, `Skeleton`, `EmptyState`, `ProgressDots`, `AudioButton`, `Avatar`.

**Caregiver:** `AssessmentQuestion`, `VerdictButtons`, `InterpretationChip`, `PropagatedAnswersCard`, `ProgressRange`, `ReportSection`, `DomainDeltaCard`, `SkillMapGrid`, `JourneyChart`, `HomeActivityCard`, `ConsentToggleList`, `ChildSwitcher`, `AccessibilityProfileForm`.

**Child:** `PlayShell` (fullscreen, wake lock, audio unlock), `InstructionBubble`, `ChoiceCard`, `MicButton`, `CaregiverOverrideButton`, `PromptLadder`, `NourCharacter` (idle / speaking / listening / celebrating — 4 states only), `SessionDots`, `ClosingScene`.

**Console:** `EscalationQueue`, `ItemBankEditor`, `SkillEditor`, `AiCallExplorer`, `GuardrailEventTable`, `FlagPanel`, `CostDashboard`.

Every component ships with a Storybook story in **both** LTR and RTL, and in light and dark where applicable. A component without an RTL story does not merge.
