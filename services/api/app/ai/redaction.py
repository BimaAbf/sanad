"""L1 — pseudonymisation and prompt-injection scrub.

Nothing identifying crosses the model boundary. Names become `{{CHILD}}` and
`{{CAREGIVER}}`, ages are rounded to whole months, governorate is dropped, and
phone/email/national-ID patterns are stripped wherever they appear.

Two Arabic-specific things this must get right, because getting them wrong is
invisible in an English test suite:

* **Combining marks.** Arabic tashkeel (َ ُ ِ ّ ْ) are separate codepoints that
  attach to the preceding letter. A naive replace can leave orphaned diacritics
  behind, producing text that renders as mojibake to a native reader. Matching is
  therefore done on a mark-stripped form while the *original* string is what gets
  substituted.
* **Hamza and ta marbuta forms.** أ إ آ ا are the same letter to a caregiver
  typing quickly, and ة/ه are routinely interchanged. A name written one way in
  the profile and another way in an answer is the same name, and both must be
  caught.

The scrub is reversible: `rehydrate` puts the real names back into model output
before a caregiver reads it, so the pseudonymisation is invisible in the product
and total at the boundary.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Substitution placeholders, not credentials.
CHILD_TOKEN = "{{CHILD}}"  # noqa: S105
CAREGIVER_TOKEN = "{{CAREGIVER}}"  # noqa: S105

#: Arabic combining marks: tashkeel, tatweel, and the superscript alef.
_ARABIC_MARKS = re.compile(r"[ً-ْـٰۖ-ۭ]")

#: Letter forms a caregiver uses interchangeably.
_NORMALISE_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
    }
)

REGEX_STRIP: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Order matters: emails contain digit runs, so they must be removed before
    # the phone pattern gets a chance to mangle them into a partial match.
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("[ID]", re.compile(r"\b\d{14}\b")),
    # The phone pattern is handled separately, by `_strip_phones`. See below.
)

#: An ISO date or timestamp. NOT a redaction pattern — the opposite.
_ISO_DATE = r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"

#: A digit run with separators. Egyptian mobiles are 11 digits, written
#: `01xxxxxxxxx`, `+201xxxxxxxxx`, and with spaces or dashes throughout.
_PHONE = r"\+?\d[\d\s\-()]{7,}\d"

#: Dates FIRST in the alternation, and this ordering is the whole fix.
#:
#: `2026-08-21` matches the phone pattern exactly — a digit, eight characters of
#: digits and separators, a digit — so every ISO date in an outgoing payload was
#: being rewritten to `[PHONE]`. A negative lookahead does not fix it: it stops
#: a match starting at the date's first character, and the engine simply
#: restarts one character in and produces `2[PHONE]`.
#:
#: Alternation with the date branch first does fix it, because the regex engine
#: consumes the whole date as a match and never offers those characters to the
#: phone branch. The date branch is then substituted with itself.
#:
#: The defect was found by `sanad rag all`: retrieved documents carry
#: `"at": "2026-08-21"`, and a milestone document reads "on 2026-08-21 this
#: skill became mastered". The model was receiving `"at": "[PHONE]"` and
#: "on [PHONE]", so it could not reason about recency at all — one of the things
#: the recommendation rubric explicitly asks it to do. Nothing failed; it
#: degraded every grounded answer silently.
#:
#: A date is not an identifier in the sense this module protects. Date of birth
#: is, and it is dropped BY KEY in FORBIDDEN_KEYS before any regex runs.
#:
#: A uuid needs the same protection for the same reason. `01a04d46-d2c9-07e5-
#: 2858-ddc734c1483f` contains `9-07e5-2858-ddc` — a digit, eight characters of
#: digits and separators, a digit — so any uuid whose middle happens to be
#: digit-heavy came out as `01a04d46-d2c[PHONE]f2-11b3ef50d0e6`. Skill ids are
#: sent to the judge and its answer is checked back against the candidate set,
#: so a mangled id is a plan that fails `CandidateSetLayer` and silently falls
#: back to the engine — visible only as a lower AI-source rate. The branch goes
#: BEFORE the phone branch for the same reason the date branch does.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

_DATE_OR_PHONE = re.compile(f"(?P<date>{_ISO_DATE})|(?P<uuid>{_UUID})|(?P<phone>{_PHONE})")


def _strip_phones(text: str) -> str:
    """Redact phone numbers, leaving ISO dates and timestamps intact."""
    return _DATE_OR_PHONE.sub(
        # Only the phone branch is redacted; the date and uuid branches
        # substitute with themselves, which is what keeps their digits out of
        # the phone branch's reach.
        lambda match: "[PHONE]" if match.group("phone") else match.group(0),
        text,
    )


#: Keys dropped from any payload outright, at any depth.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "date_of_birth",
        "dob",
        "governorate",
        "phone_e164",
        "phone",
        "email",
        "address",
        "national_id",
        "display_name",
        "name_vowelised",
        "caregiver_name",
        "child_name",
        "audio",
        "audio_url",
        "password_hash",
        "play_pin_hash",
    }
)

#: Keys whose numeric value is an age in months and must be rounded.
AGE_KEYS: frozenset[str] = frozenset(
    {"age_months", "child_months", "chronological_months", "corrected_months"}
)

#: Caregiver free text is wrapped so the system prompt can state that anything
#: inside is data describing a child, never an instruction.
ANSWER_OPEN = "<caregiver_answer>"
ANSWER_CLOSE = "</caregiver_answer>"

#: Instruction-shaped phrases stripped from caregiver text before it is wrapped.
#: The delimiters are the real defence; this is belt and braces for the obvious.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bignore (all |your |previous |the )*(instructions?|rules?|prompt)"),
    re.compile(r"(?i)\bdisregard (all |your |previous |the )*(instructions?|rules?)"),
    re.compile(r"(?i)\byou are (now )?(a|an) \w+"),
    re.compile(r"(?i)\bsystem prompt\b"),
    re.compile(r"(?i)\bnew instructions?\b"),
    re.compile(r"(?i)</?(system|assistant|human)>"),
    re.compile(r"تجاهل (كل )?(التعليمات|القواعد)"),
    re.compile(r"انت دلوقتي"),
)


def normalise(text: str) -> str:
    """Fold marks and letter variants so two spellings of a name compare equal."""
    folded = unicodedata.normalize("NFC", text)
    folded = _ARABIC_MARKS.sub("", folded)
    return folded.translate(_NORMALISE_MAP).casefold()


def strip_injection(text: str) -> str:
    scrubbed = text
    for pattern in _INJECTION_PATTERNS:
        scrubbed = pattern.sub("[REMOVED]", scrubbed)
    # Never let caregiver text close the wrapper it is about to be placed in.
    return scrubbed.replace(ANSWER_OPEN, "").replace(ANSWER_CLOSE, "")


def wrap_caregiver_text(text: str) -> str:
    """Delimit caregiver free text as data, not instruction."""
    return f"{ANSWER_OPEN}{strip_injection(text)}{ANSWER_CLOSE}"


def round_age_months(value: float) -> int:
    """Whole months only. A date of birth never crosses the boundary."""
    return round(value)


@dataclass(slots=True)
class Pseudonymiser:
    """Reversible, per-request. Nothing identifying crosses the API boundary."""

    child_name: str | None = None
    caregiver_name: str | None = None
    #: Extra names to redact — siblings mentioned in an answer, for instance.
    extra_names: Sequence[str] = ()
    _replacements: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._replacements = {}
        if self.child_name:
            self._replacements[CHILD_TOKEN] = self.child_name
        if self.caregiver_name:
            self._replacements[CAREGIVER_TOKEN] = self.caregiver_name

    def _name_patterns(self) -> list[tuple[str, str]]:
        """(normalised name, token), longest first.

        Longest first so that a two-part name is replaced whole rather than
        having its first token swapped and the surname left behind.
        """
        pairs: list[tuple[str, str]] = []
        if self.child_name:
            pairs.append((normalise(self.child_name), CHILD_TOKEN))
        if self.caregiver_name:
            pairs.append((normalise(self.caregiver_name), CAREGIVER_TOKEN))
        for name in self.extra_names:
            pairs.append((normalise(name), "{{PERSON}}"))
        return sorted(pairs, key=lambda pair: -len(pair[0]))

    def scrub_text(self, text: str) -> str:
        """Replace names and strip identifying patterns from one string.

        Matching happens on a normalised copy while the substitution is applied
        to the original, so the surrounding Arabic keeps its diacritics intact.
        """
        result = text
        for name, token in self._name_patterns():
            if not name:
                continue
            result = self._replace_normalised(result, name, token)
        for replacement, pattern in REGEX_STRIP:
            result = pattern.sub(replacement, result)
        # Last, and separately: it has to protect dates while redacting phones,
        # which a (token, pattern) pair cannot express.
        return _strip_phones(result)

    @staticmethod
    def _replace_normalised(text: str, needle: str, token: str) -> str:
        """Replace every occurrence of `needle` (normalised) in `text`.

        Walks the original string keeping a parallel normalised index, so a name
        written with tashkeel in the profile still matches one written without
        it in a caregiver's answer, and vice versa.
        """
        if not needle:
            return text
        # Build a map from normalised position -> original position.
        original_positions: list[int] = []
        normalised_chars: list[str] = []
        for index, char in enumerate(unicodedata.normalize("NFC", text)):
            folded = normalise(char)
            for _ in folded:
                original_positions.append(index)
            normalised_chars.append(folded)
        normalised = "".join(normalised_chars)

        out: list[str] = []
        cursor = 0
        search_from = 0
        while True:
            found = normalised.find(needle, search_from)
            if found == -1:
                break
            start = original_positions[found]
            end_index = found + len(needle) - 1
            end = (
                original_positions[end_index] + 1
                if end_index < len(original_positions)
                else len(text)
            )
            out.append(text[cursor:start])
            out.append(token)
            cursor = end
            search_from = end_index + 1
        out.append(text[cursor:])
        return "".join(out)

    def scrub(self, payload: Any) -> Any:
        """Recursively scrub a JSON-shaped payload.

        Forbidden keys are dropped rather than emptied: an empty `date_of_birth`
        key still tells the model that a date of birth exists and is being
        withheld, which is more information than it needs.
        """
        if isinstance(payload, Mapping):
            cleaned: dict[str, Any] = {}
            for key, value in payload.items():
                lowered = str(key).lower()
                if lowered in FORBIDDEN_KEYS:
                    continue
                if lowered in AGE_KEYS and isinstance(value, int | float):
                    cleaned[str(key)] = round_age_months(float(value))
                    continue
                cleaned[str(key)] = self.scrub(value)
            return cleaned
        if isinstance(payload, list | tuple):
            return [self.scrub(item) for item in payload]
        if isinstance(payload, str):
            return self.scrub_text(payload)
        return payload

    def rehydrate(self, text: str) -> str:
        """Put the real names back, for display to the caregiver only."""
        result = text
        for token, name in self._replacements.items():
            result = result.replace(token, name)
        return result


def contains_identifier(payload: Any, identifiers: Sequence[str]) -> list[str]:
    """Any identifier still present in a payload. Empty means clean.

    Used by the outgoing-payload assertion: the test that no value from the
    children table ever appears in a request.
    """
    serialised = repr(payload)
    normalised = normalise(serialised)
    found = []
    for identifier in identifiers:
        if not identifier:
            continue
        if normalise(identifier) in normalised:
            found.append(identifier)
    return found
