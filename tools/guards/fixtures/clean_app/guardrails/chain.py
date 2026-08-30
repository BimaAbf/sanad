"""CONTROL FIXTURE — required-guardrail-layer guard must PASS on this file.

pgee_report produces prose a caregiver reads AND restates computed numbers, so
it needs both ClinicalSafetyLayer and NumericEqualityLayer. Both are here.
"""


class ClinicalSafetyLayer: ...


class NumericEqualityLayer: ...


class CandidateSetLayer: ...


class ClosedEnumLayer: ...


LAYERS = {
    "pgee_next_item": [CandidateSetLayer],
    "pgee_interpret": [ClosedEnumLayer],
    "pgee_probe": [ClinicalSafetyLayer],
    "pgee_report": [ClinicalSafetyLayer, NumericEqualityLayer],
    "tutor_plan": [CandidateSetLayer],
    # The per-activity teaching decision: it picks from a candidate set AND
    # every field it returns is a closed set, so it carries both.
    "tutor_brain": [CandidateSetLayer, ClosedEnumLayer],
    "tutor_judge": [ClosedEnumLayer],
    "tutor_summary": [ClinicalSafetyLayer],
    "safety_classify": [ClinicalSafetyLayer],
    # The two chat surfaces. `child_chat` takes CandidateSetLayer rather than a
    # safety layer because it generates nothing: it classifies an utterance into
    # one of seven reviewed phrases, so the candidate set IS the safety property.
    "caregiver_chat": [ClinicalSafetyLayer],
    "child_chat": [CandidateSetLayer],
}
