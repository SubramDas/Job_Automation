"""Regression checks for keyword-bearing Agent C suggestions."""

from __future__ import annotations

import copy
import unittest

from app.profile.resume_suggestions import validate_suggestions


class AgentCKeywordCoverageTests(unittest.TestCase):
    def test_saved_plan_term_must_appear_in_each_proposed_line(self) -> None:
        resume = "# Technical Skills\n- Python\n"
        plan = [{"term": "Python automation", "exact_terms": ["Python automation"], "synonyms": []}]
        variants = []
        for line in (
            "[Only if true] Python automation for build checks.",
            "[Only if true] Python automation for model evaluations.",
            "[Only if true] Python automation for data validation.",
        ):
            variants.append(
                {
                    "action": "add_new_line",
                    "section_or_project": "Technical Skills",
                    "resume_pointer": "- Python",
                    "proposed_line": line,
                    "evidence_basis": "No direct resume evidence",
                    "verification_needed": "Confirm the stated automation work.",
                    "rationale": "Conditional: insert after the quoted resume pointer.",
                }
            )
        payload = {"keyword_suggestions": [{"keyword": "Python automation", "suggestions": variants}]}
        self.assertEqual(validate_suggestions(payload, resume, plan)["status"], "passed")

        missing_term = copy.deepcopy(payload)
        missing_term["keyword_suggestions"][0]["suggestions"][1]["proposed_line"] = "[Only if true] Built model evaluation scripts."
        findings = validate_suggestions(missing_term, resume, plan)["findings"]
        self.assertIn("keyword_suggestion_1_variant_2_keyword_missing_from_line", {item["code"] for item in findings})


if __name__ == "__main__":
    unittest.main()
