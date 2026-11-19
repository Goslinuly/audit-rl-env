"""Reference answer built from truth — for tests and the grader self-check only.

Participant 4's ``OraclePolicy`` receives truth from the runner; this helper produces the
same findings so grader tests do not depend on the policies package.
"""

from __future__ import annotations


def oracle_findings(truth: dict, *, evidence_set: int = 0) -> dict:
    return {
        "episode_id": truth["episode_id"],
        "findings": [
            {
                "type": i["type"],
                "affected_ids": list(i["affected_ids"]),
                "claimed_amount_minor": i["expected_amount_minor"],
                "currency": i["currency"],
                "evidence_ids": list(i["evidence_sets"][min(evidence_set, len(i["evidence_sets"]) - 1)]),
                "explanation": f"{i['type']} on {', '.join(i['affected_ids'])}",
            }
            for i in truth["issues"]
        ],
    }
