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
    "tutor_judge": [ClosedEnumLayer],
    "tutor_summary": [ClinicalSafetyLayer],
    "safety_classify": [ClinicalSafetyLayer],
}
