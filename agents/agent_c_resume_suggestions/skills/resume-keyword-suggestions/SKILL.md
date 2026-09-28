# Skill: resume keyword suggestions

Use after a saved job has a validated Agent A keyword plan and Agent C context access is approved.

1. Read the assigned context through `agent_c_get_suggestion_context`; do not request other files or profile fields.
2. If the user supplied a resume path, import it with `agent_c_import_resume`. If the current source hash has no conversion, create clean Markdown from the returned TeX while preserving all facts and project boundaries, then store it through `agent_c_save_resume_markdown`. Retry the context tool after saving.
3. Identify the resume's project headings and preserve their exact boundaries.
4. For every keyword in the saved plan, return exactly three distinct line suggestions. Each names a resume section or exact project and points to exact existing resume text.
5. Hypothetical claims are allowed; use the resume pointer to show where the suggestion could fit. Keep project suggestions inside that same project and do not mix or reassign projects.
6. Keep each proposed rendered line no longer than its resume pointer. The user verifies every suggestion and applies any changes manually.
7. Call `agent_c_save_suggestions`. Resolve validation findings by correcting the output, not by weakening checks.
8. Return artifact ID, validation status, review path, and a reminder that the user chooses and edits manually.

If the best placement is unclear, still offer three pointer-anchored possibilities and explain the uncertainty. The user reviews and applies suggestions manually.
