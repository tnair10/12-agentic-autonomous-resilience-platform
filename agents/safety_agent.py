#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


SAFE_ACTIONS = {
    "tls_failure": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "database_latency": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "authentication_failure": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "retry_storm": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "consumer_slowdown": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "jvm_memory_pressure": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
    "gc_storm": {
        "action": "reset_workload",
        "risk": "low",
        "description": "Restore the local workload simulator to normal state",
    },
}


def load_json(path):
    return json.loads(
        Path(path).read_text()
    )


def assess(fusion):
    root = fusion.get(
        "final_root_cause"
    )

    confidence = float(
        fusion.get(
            "final_confidence",
            0,
        )
    )

    action = SAFE_ACTIONS.get(
        root
    )

    reasons = []

    if not action:
        return {
            "decision": "HUMAN_APPROVAL_REQUIRED",
            "root_cause": root,
            "confidence": confidence,
            "action": None,
            "risk": "unknown",
            "reasons": [
                "No approved deterministic remediation exists for this root cause."
            ],
        }

    if confidence < 0.70:
        return {
            "decision": "HUMAN_APPROVAL_REQUIRED",
            "root_cause": root,
            "confidence": confidence,
            "action": action["action"],
            "risk": action["risk"],
            "reasons": [
                "Diagnosis confidence is below the autonomous execution threshold."
            ],
        }

    if action["risk"] != "low":
        return {
            "decision": "HUMAN_APPROVAL_REQUIRED",
            "root_cause": root,
            "confidence": confidence,
            "action": action["action"],
            "risk": action["risk"],
            "reasons": [
                "Only low-risk actions may execute autonomously."
            ],
        }

    reasons.append(
        "Final diagnostic confidence is at least 0.70."
    )

    reasons.append(
        "Action is present in the deterministic remediation allowlist."
    )

    reasons.append(
        "Action affects only the local Project 12 workload simulator."
    )

    return {
        "decision": "AUTO_EXECUTE",
        "root_cause": root,
        "confidence": confidence,
        "action": action["action"],
        "risk": action["risk"],
        "description": action["description"],
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Project 12 remediation safety agent"
    )

    parser.add_argument(
        "--fusion",
        default="results/incidents/latest-fusion.json",
    )

    parser.add_argument(
        "--output",
        default="results/incidents/latest-safety.json",
    )

    args = parser.parse_args()

    fusion = load_json(
        args.fusion
    )

    result = assess(
        fusion
    )

    Path(
        args.output
    ).write_text(
        json.dumps(
            result,
            indent=2,
        )
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print(
        f"SAFETY_WRITTEN={args.output}"
    )

    print(
        "SAFETY_AGENT=PASS"
    )


if __name__ == "__main__":
    main()
