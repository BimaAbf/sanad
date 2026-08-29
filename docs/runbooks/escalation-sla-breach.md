# Escalation SLA breach

An escalation is a caregiver own words about their child, flagged by a safety
guardrail. The SLA is not an operational metric; it is how long a worried parent
waits for an answer.

## Immediately

1. `/console/escalations?status=open&sort=sla` — the queue is already ordered by
   what is closest to breaching.
2. Severity 1 pages the on-call clinician directly. If they have not
   acknowledged within the paging window, escalate to the clinical lead. **Do
   not wait for the SLA to expire before escalating**: the SLA is the deadline
   for the caregiver answer, not the deadline for starting work on it.

## If no clinician is reachable

The caregiver receives a human-written apology and a signposting message. Not an
automated one, and not an AI-generated one: a family who raised a concern about
their child and got a templated reply has been told plainly that nobody read it.

The signposting message names real services. It offers no advice and attempts no
reassurance about the specific concern — that is the clinician job, and it is
exactly the thing we are currently late on.

## Do not

- Do not resolve an escalation to clear the queue. `dismissed` and `resolved`
  are different states for a reason and both are audited.
- Do not let a model draft the reply. docs/03 places escalation responses outside
  what any model may generate, and an outage is not the moment to find out why.

## After

An SLA breach is a process finding, not an individual one. Record the queue
depth, what else was happening at the time, and whether the paging path actually
worked — by far the most common cause is that the page went somewhere nobody was
looking.
