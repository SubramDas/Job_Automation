# Skill: resume keyword suggestions

Use after a saved job has a validated Agent A keyword plan and Agent C context access is approved.

1. If the user supplied a resume path, import it with `agent_c_import_resume`. If the current source hash has no conversion, create clean Markdown from the returned TeX while preserving all facts and project boundaries, then store it through `agent_c_save_resume_markdown`.
2. Call `agent_c_generate_suggestions` with the assigned saved job ID. It loads the canonical prompt, cached resume Markdown, and assigned keyword plan, calls Gemini 3.6 Flash at high thinking, validates exactly three suggestions per keyword, and saves the artifact.
3. Return the artifact ID, review path, and a reminder that the user chooses and edits manually. If validation fails after the bounded repair, report the failure without weakening checks or generating lines in the Codex session.

If the best placement is unclear, still offer three pointer-anchored possibilities and explain the uncertainty. The user reviews and applies suggestions manually.
