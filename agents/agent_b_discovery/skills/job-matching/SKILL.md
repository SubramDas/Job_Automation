# Skill: Job Matching

## Trigger

Use after extraction to decide whether a job is rejected, reviewed, or shortlisted.

## Procedure

1. Apply hard constraints before scoring.
2. For each hard constraint, record known pass, known fail, or unknown.
3. Reject only known hard failures.
4. Send unknown critical constraints to review.
5. Score flexible preferences with evidence-linked explanations.
6. Report gaps and evidence coverage alongside the score.

## Initial Policy Notes

Onsite and hybrid roles must be in Bengaluru or Hyderabad. Remote roles may be elsewhere.
Full-time permanent roles seeking 1-3 years are the initial target. Compensation filtering
applies only when compatible compensation is stated.

## Examples

Positive: A full-time remote Python role asking for two years of experience may proceed to
scoring even when the employer city is elsewhere.

Negative: A known onsite role in Pune fails the current location hard constraint.

Adversarial: A posting says "location flexible after applying" but lists onsite Pune only.
Use extracted facts and route genuine ambiguity to review.

## Output

Return hard-filter evidence, weighted score, coverage, gaps, review reason if any, and the
next recommended workflow state.

