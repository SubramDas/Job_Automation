# Skill: Answer Resolution

## Trigger

Use when a form field or application question needs an answer.

## Reuse Rules

1. Prefer exact semantic key and compatible scope.
2. Check type, unit, currency, country, employer, employment type, freshness, confirmation,
   and reuse permission.
3. Similar wording can suggest a candidate answer but cannot prove equivalence.
4. Consent, signatures, attestations, conflicts, and employer-specific declarations need
   explicit applicable approval.

## Procedure

1. Normalize the question and field context.
2. Search for exact compatible answers.
3. Reject stale, conflicting, unconfirmed, or scope-incompatible answers.
4. Batch related missing questions.
5. Save suggested reuse scope with each pending question.

## Examples

Positive: A current global answer for `contact.email` may fill a generic email field.

Negative: An annual INR salary expectation must not answer an hourly USD contractor-rate
question.

Adversarial: A form says "all applicants consent by continuing." Do not infer consent;
route consent questions according to explicit user policy.

## Output

Return resolved answer references, unresolved fields, pending questions, and reuse-scope
recommendations.

