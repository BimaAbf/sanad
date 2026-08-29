/**
 * Scale-to-zero GPU for Qwen3-ASR. docs/12 §Δ3.
 *
 * docs/12 §3.3 is explicit that a single always-on A6000 must NOT be the
 * production ASR tier without redundancy: one GPU on one provider is a single
 * point of failure in a live child-facing path. So this module provisions the
 * GPU *and* asserts that a failover is configured, and the health check that
 * decides failover lives outside the GPU's own account.
 *
 * Three layers deep, and the third needs no vendor at all:
 *     Qwen (here) -> Groq Whisper -> caregiver confirmation
 */

variable "name" { type = string }
variable "enabled" {
  type    = bool
  default = false
}
variable "groq_whisper_failover_configured" {
  type        = bool
  description = "Set by the secrets module once a Groq key exists."
}
variable "idle_shutdown_minutes" {
  type    = number
  default = 15
}

# The one hard gate in this module. A GPU tier without a failover is worse than
# no GPU tier, because the fallback path then goes untested until the night it
# is needed.
resource "terraform_data" "failover_required" {
  lifecycle {
    precondition {
      condition     = !var.enabled || var.groq_whisper_failover_configured
      error_message = "A self-hosted ASR tier requires the Groq Whisper failover to be configured (docs/12 §3.3)."
    }
  }
}

output "notes" {
  value = join(" ", [
    "Provider-specific GPU resources are intentionally absent:",
    "the pilot uses Groq's free Whisper tier and NO GPU at all (docs/12 §3.3),",
    "and self-hosted ASR arrives only when a fine-tuned model justifies it.",
    "This module exists to hold the failover precondition and the shutdown policy",
    "so that turning the tier on cannot skip either."
  ])
}

output "idle_shutdown_minutes" { value = var.idle_shutdown_minutes }
