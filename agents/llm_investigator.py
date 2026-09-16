#!/usr/bin/env python3

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

DEFAULT_MODEL = "qwen2.5:3b"


def load_json(path):
    return json.loads(
        Path(path).read_text()
    )


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def compact_telemetry(data):
    metrics = data.get(
        "metrics",
        {},
    )

    result = {}

    for name, values in metrics.items():
        result[name] = values

    result["derived"] = data.get(
        "derived",
        {},
    )

    result["target_up"] = data.get(
        "target_up"
    )

    result["window"] = data.get(
        "window"
    )

    return result


def compact_hypotheses(data):
    return [
        {
            "rank":
                item.get("rank"),

            "hypothesis":
                item.get(
                    "hypothesis"
                ),

            "confidence":
                item.get(
                    "confidence"
                ),

            "raw_score":
                item.get(
                    "raw_score"
                ),

            "supporting_evidence":
                item.get(
                    "supporting_evidence",
                    [],
                ),

            "contradicting_evidence":
                item.get(
                    "contradicting_evidence",
                    [],
                ),

            "recommended_action":
                item.get(
                    "recommended_action"
                ),
        }
        for item in data.get(
            "hypotheses",
            [],
        )
    ]


def compact_causal(data):
    return {
        "causal_root_signal":
            data.get(
                "causal_root_signal"
            ),

        "top_hypothesis":
            data.get(
                "top_hypothesis"
            ),

        "hypothesis_causal_agreement":
            data.get(
                "hypothesis_causal_agreement"
            ),

        "timeline":
            data.get(
                "timeline",
                [],
            ),

        "causal_links":
            data.get(
                "causal_links",
                [],
            ),

        "causal_paths":
            data.get(
                "causal_paths",
                [],
            ),
    }


def build_prompt(
    telemetry,
    hypotheses,
    causal,
):
    evidence = {
        "telemetry":
            compact_telemetry(
                telemetry
            ),

        "hypotheses":
            compact_hypotheses(
                hypotheses
            ),

        "causal_analysis":
            compact_causal(
                causal
            ),
    }

    return f"""
You are the Project 12 Incident Investigation Agent.

You are investigating a distributed-system incident.

STRICT RULES:

1. Use ONLY the supplied evidence.
2. Do not invent metrics, logs, events, services, or causes.
3. Separate root cause from downstream symptoms.
4. Consider competing hypotheses.
5. Explicitly mention evidence that rejects alternatives.
6. If evidence is insufficient, state that clearly.
7. Do not claim causal certainty from timestamp ordering alone.
8. Do not execute remediation.
9. Return JSON only.
10. Confidence must be a number between 0 and 1.

Return exactly this JSON structure:

{{
  "incident_classification": "...",
  "root_cause": "...",
  "confidence": 0.0,
  "executive_summary": "...",
  "causal_chain": [
    "..."
  ],
  "supporting_evidence": [
    "..."
  ],
  "rejected_hypotheses": [
    {{
      "hypothesis": "...",
      "reason": "..."
    }}
  ],
  "recommended_verification": [
    "..."
  ],
  "recommended_remediation": [
    "..."
  ],
  "safety_notes": [
    "..."
  ]
}}

EVIDENCE:

{json.dumps(evidence, indent=2)}
""".strip()


def call_ollama(
    model,
    prompt,
):
    payload = {
        "model":
            model,

        "stream":
            False,

        "format":
            "json",

        "options": {
            "temperature":
                0.1,
        },

        "messages": [
            {
                "role":
                    "system",

                "content":
                    (
                        "You are a grounded SRE "
                        "incident investigator. "
                        "Never invent evidence."
                    ),
            },
            {
                "role":
                    "user",

                "content":
                    prompt,
            },
        ],
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=180,
    )

    response.raise_for_status()

    data = response.json()

    content = (
        data
        .get("message", {})
        .get("content", "")
    )

    if not content:
        raise RuntimeError(
            "Ollama returned empty content"
        )

    return json.loads(
        content
    )


def validate_result(result):
    required = [
        "incident_classification",
        "root_cause",
        "confidence",
        "executive_summary",
        "causal_chain",
        "supporting_evidence",
        "rejected_hypotheses",
        "recommended_verification",
        "recommended_remediation",
        "safety_notes",
    ]

    missing = [
        key
        for key in required
        if key not in result
    ]

    if missing:
        raise RuntimeError(
            "Missing LLM fields: "
            + ", ".join(missing)
        )

    confidence = result.get(
        "confidence"
    )

    if not isinstance(
        confidence,
        (int, float),
    ):
        raise RuntimeError(
            "LLM confidence is not numeric"
        )

    if not (
        0 <= confidence <= 1
    ):
        raise RuntimeError(
            "LLM confidence outside 0-1"
        )


def write_markdown(
    result,
    path,
):
    lines = [
        "# Project 12 Incident Investigation",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Classification",
        "",
        result[
            "incident_classification"
        ],
        "",
        "## Root Cause",
        "",
        result[
            "root_cause"
        ],
        "",
        "## Confidence",
        "",
        str(
            result[
                "confidence"
            ]
        ),
        "",
        "## Executive Summary",
        "",
        result[
            "executive_summary"
        ],
        "",
        "## Causal Chain",
        "",
    ]

    for item in result[
        "causal_chain"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.extend(
        [
            "",
            "## Supporting Evidence",
            "",
        ]
    )

    for item in result[
        "supporting_evidence"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.extend(
        [
            "",
            "## Rejected Hypotheses",
            "",
        ]
    )

    for item in result[
        "rejected_hypotheses"
    ]:
        lines.append(
            "- "
            + item.get(
                "hypothesis",
                "unknown",
            )
            + ": "
            + item.get(
                "reason",
                "",
            )
        )

    lines.extend(
        [
            "",
            "## Recommended Verification",
            "",
        ]
    )

    for item in result[
        "recommended_verification"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.extend(
        [
            "",
            "## Recommended Remediation",
            "",
        ]
    )

    for item in result[
        "recommended_remediation"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.extend(
        [
            "",
            "## Safety Notes",
            "",
        ]
    )

    for item in result[
        "safety_notes"
    ]:
        lines.append(
            f"- {item}"
        )

    Path(path).write_text(
        "\n".join(lines)
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Project 12 grounded "
            "local-LLM investigator"
        )
    )

    parser.add_argument(
        "--telemetry",
        default=(
            "results/incidents/"
            "latest-telemetry.json"
        ),
    )

    parser.add_argument(
        "--hypotheses",
        default=(
            "results/incidents/"
            "latest-hypotheses.json"
        ),
    )

    parser.add_argument(
        "--causal",
        default=(
            "results/incidents/"
            "latest-causal-analysis.json"
        ),
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
    )

    parser.add_argument(
        "--output",
        default=(
            "results/incidents/"
            "latest-llm-investigation.json"
        ),
    )

    parser.add_argument(
        "--markdown",
        default=(
            "results/incidents/"
            "latest-llm-investigation.md"
        ),
    )

    args = parser.parse_args()

    telemetry = load_json(
        args.telemetry
    )

    hypotheses = load_json(
        args.hypotheses
    )

    causal = load_json(
        args.causal
    )

    prompt = build_prompt(
        telemetry,
        hypotheses,
        causal,
    )

    print(
        f"OLLAMA_MODEL={args.model}"
    )

    print(
        "LLM_INVESTIGATION=RUNNING"
    )

    result = call_ollama(
        args.model,
        prompt,
    )

    validate_result(
        result
    )

    result[
        "generated_at"
    ] = utc_now()

    result[
        "model"
    ] = args.model

    Path(
        args.output
    ).write_text(
        json.dumps(
            result,
            indent=2,
        )
    )

    write_markdown(
        result,
        args.markdown,
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()

    print(
        f"LLM_JSON={args.output}"
    )

    print(
        f"LLM_MARKDOWN={args.markdown}"
    )

    print(
        "LLM_INVESTIGATOR=PASS"
    )


if __name__ == "__main__":
    main()
