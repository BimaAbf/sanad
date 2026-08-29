/**
 * The alerts from docs/08 §5 that page, as code.
 *
 * Every threshold is transcribed from that table rather than invented. Two are
 * worth flagging because they look wrong until you know why:
 *
 *   * "L5 safety block — ANY occurrence". Not a rate. An L5 block means the
 *     clinical-safety layer stopped something before it reached a caregiver,
 *     and a human needs to read it the same day.
 *   * "Cache read ratio < 60% over 1h". This looks like a cost alarm and is
 *     really a correctness alarm: a collapsed cache ratio means dynamic text
 *     has crept into a prompt prefix, which usually means something
 *     identifying is now being sent on every call.
 */

variable "name" { type = string }
variable "sns_topic_arn" { type = string }

locals {
  alarms = {
    l5_safety_block = {
      metric      = "guardrail.l5_block"
      threshold   = 0
      periods     = 1
      period      = 60
      comparison  = "GreaterThanThreshold"
      description = "A clinical-safety layer blocked output. Any occurrence pages."
    }
    guardrail_rejection_rate = {
      metric      = "guardrail.rejection_rate"
      threshold   = 0.005
      periods     = 1
      period      = 86400
      comparison  = "GreaterThanThreshold"
      description = "docs/08 §5: > 0.5% / 24h per decision point."
    }
    cache_read_ratio = {
      metric      = "ai.cache_read_ratio"
      threshold   = 0.6
      periods     = 1
      period      = 3600
      comparison  = "LessThanThreshold"
      description = "Below 60% means dynamic text has entered a cached prefix."
    }
    cost_per_child_day = {
      metric      = "cost.per_child_day_usd"
      threshold   = 0.4
      periods     = 1
      period      = 3600
      comparison  = "GreaterThanThreshold"
      description = "The soft budget from docs/04a §C15."
    }
    queue_depth = {
      metric      = "arq.queue_depth"
      threshold   = 500
      periods     = 2
      period      = 300
      comparison  = "GreaterThanThreshold"
      description = "docs/08 §5: > 500 for 10 minutes."
    }
    db_connections = {
      metric      = "rds.connection_utilisation"
      threshold   = 0.8
      periods     = 2
      period      = 300
      comparison  = "GreaterThanThreshold"
      description = "80% of max connections."
    }
    failed_migration = {
      metric      = "deploy.migration_failed"
      threshold   = 0
      periods     = 1
      period      = 60
      comparison  = "GreaterThanThreshold"
      description = "A failed Alembic migration pages immediately."
    }
    escalation_severity_1 = {
      metric      = "safety.escalation_severity_1"
      threshold   = 0
      periods     = 1
      period      = 60
      comparison  = "GreaterThanThreshold"
      description = "A severity-1 escalation pages immediately."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "paging" {
  for_each = local.alarms

  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = "Sanad"
  metric_name         = each.value.metric
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  evaluation_periods  = each.value.periods
  period              = each.value.period
  statistic           = "Average"
  # A metric that stops arriving is not an incident by itself; the uptime check
  # covers "the service is gone". Alarming on missing data here would page
  # someone every time a low-volume decision point had a quiet hour.
  treat_missing_data = "notBreaching"
  alarm_actions      = [var.sns_topic_arn]
  ok_actions         = [var.sns_topic_arn]
}

output "alarm_names" {
  value = [for alarm in aws_cloudwatch_metric_alarm.paging : alarm.alarm_name]
}
