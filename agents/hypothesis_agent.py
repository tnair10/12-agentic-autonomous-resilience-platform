#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def metric(evidence, name, field):
    return (
        evidence
        .get("metrics", {})
        .get(name, {})
        .get(field)
    )


def detect_features(evidence):
    latency_current = (
        metric(
            evidence,
            "latency_ms",
            "current",
        )
        or 0
    )

    latency_peak = (
        metric(
            evidence,
            "latency_ms",
            "peak",
        )
        or 0
    )

    error_peak = (
        metric(
            evidence,
            "error_rate",
            "peak",
        )
        or 0
    )

    lag_peak = (
        metric(
            evidence,
            "consumer_lag",
            "peak",
        )
        or 0
    )

    queue_peak = (
        metric(
            evidence,
            "queue_depth",
            "peak",
        )
        or 0
    )

    db_peak = (
        metric(
            evidence,
            "database_latency_ms",
            "peak",
        )
        or 0
    )

    tls_delta = (
        metric(
            evidence,
            "tls_failures",
            "delta",
        )
        or 0
    )

    auth_delta = (
        metric(
            evidence,
            "authentication_failures",
            "delta",
        )
        or 0
    )

    retry_delta = (
        metric(
            evidence,
            "retry_count",
            "delta",
        )
        or 0
    )

    heap_peak = (
        metric(
            evidence,
            "heap_used_bytes",
            "peak",
        )
        or 0
    )

    heap_max = (
        metric(
            evidence,
            "heap_max_bytes",
            "current",
        )
        or 1
    )

    gc_delta = (
        metric(
            evidence,
            "young_gc_count",
            "delta",
        )
        or 0
    )

    heap_peak_percent = (
        heap_peak
        / heap_max
        * 100
    )

    return {
        "latency_spike":
            latency_peak >= 500
            and latency_peak
            >= latency_current * 2,

        "error_spike":
            error_peak >= 0.05,

        "consumer_lag_spike":
            lag_peak >= 1000,

        "queue_depth_spike":
            queue_peak >= 50,

        "database_latency_spike":
            db_peak >= 500,

        "tls_failures":
            tls_delta > 0,

        "authentication_failures":
            auth_delta > 0,

        "retry_storm":
            retry_delta >= 100,

        "heap_pressure":
            heap_peak_percent >= 70,

        "gc_pressure":
            gc_delta >= 3,

        "heap_peak_percent":
            round(
                heap_peak_percent,
                2,
            ),

        "values": {
            "latency_peak_ms":
                latency_peak,

            "error_rate_peak":
                error_peak,

            "consumer_lag_peak":
                lag_peak,

            "queue_depth_peak":
                queue_peak,

            "database_latency_peak_ms":
                db_peak,

            "tls_failure_delta":
                tls_delta,

            "authentication_failure_delta":
                auth_delta,

            "retry_delta":
                retry_delta,

            "young_gc_delta":
                gc_delta,
        },
    }


HYPOTHESES = {
    "tls_failure": {
        "title":
            "TLS / trust-chain failure",

        "supports": {
            "tls_failures": 6.0,
            "retry_storm": 2.0,
            "error_spike": 2.0,
            "latency_spike": 1.5,
            "consumer_lag_spike": 1.0,
            "queue_depth_spike": 1.0,
        },

        "contradicts": {
            "database_latency_spike": 1.0,
            "authentication_failures": 1.0,
            "heap_pressure": 1.0,
            "gc_pressure": 0.5,
        },

        "root_cause":
            "tls_handshake_failure",

        "recommended_action":
            "validate certificate, truststore, "
            "SAN chain, and TLS endpoint",
    },

    "authentication_failure": {
        "title":
            "Authentication service failure",

        "supports": {
            "authentication_failures": 6.0,
            "error_spike": 2.0,
            "retry_storm": 2.0,
            "latency_spike": 1.0,
        },

        "contradicts": {
            "tls_failures": 2.0,
            "database_latency_spike": 1.0,
            "heap_pressure": 0.5,
        },

        "root_cause":
            "authentication_service_failure",

        "recommended_action":
            "validate identity provider, LDAP, "
            "Kerberos, credentials, and authorization",
    },

    "database_latency": {
        "title":
            "Downstream database degradation",

        "supports": {
            "database_latency_spike": 6.0,
            "latency_spike": 2.0,
            "queue_depth_spike": 2.0,
            "retry_storm": 1.0,
            "consumer_lag_spike": 1.0,
        },

        "contradicts": {
            "tls_failures": 1.5,
            "authentication_failures": 1.0,
            "heap_pressure": 0.5,
        },

        "root_cause":
            "downstream_database_latency",

        "recommended_action":
            "investigate database latency, locks, "
            "connections, and downstream saturation",
    },

    "consumer_slowdown": {
        "title":
            "Consumer processing degradation",

        "supports": {
            "consumer_lag_spike": 4.0,
            "queue_depth_spike": 3.0,
            "latency_spike": 1.0,
        },

        "contradicts": {
            "tls_failures": 2.0,
            "authentication_failures": 1.5,
            "database_latency_spike": 1.0,
        },

        "root_cause":
            "consumer_processing_degradation",

        "recommended_action":
            "inspect consumer throughput, worker "
            "capacity, and processing bottlenecks",
    },

    "retry_storm": {
        "title":
            "Retry amplification / retry storm",

        "supports": {
            "retry_storm": 5.0,
            "queue_depth_spike": 2.0,
            "consumer_lag_spike": 2.0,
            "latency_spike": 1.0,
            "error_spike": 1.0,
        },

        "contradicts": {
            "tls_failures": 1.5,
            "authentication_failures": 1.5,
            "database_latency_spike": 1.0,
        },

        "root_cause":
            "uncontrolled_retry_amplification",

        "recommended_action":
            "inspect retry policy, backoff, "
            "circuit breakers, and upstream trigger",
    },

    "jvm_memory_pressure": {
        "title":
            "JVM memory pressure",

        "supports": {
            "heap_pressure": 6.0,
            "latency_spike": 1.5,
            "queue_depth_spike": 1.0,
            "gc_pressure": 1.0,
        },

        "contradicts": {
            "tls_failures": 1.5,
            "authentication_failures": 1.0,
            "database_latency_spike": 1.0,
        },

        "root_cause":
            "sustained_heap_growth",

        "recommended_action":
            "inspect heap growth, allocations, "
            "retained objects, and memory limits",
    },

    "gc_storm": {
        "title":
            "Excessive JVM garbage collection",

        "supports": {
            "gc_pressure": 6.0,
            "latency_spike": 2.0,
            "retry_storm": 1.0,
        },

        "contradicts": {
            "tls_failures": 1.5,
            "authentication_failures": 1.0,
            "database_latency_spike": 1.0,
        },

        "root_cause":
            "excessive_allocation_rate",

        "recommended_action":
            "inspect allocation rate, GC pauses, "
            "heap sizing, and object churn",
    },
}


def score_hypothesis(
    name,
    definition,
    features,
):
    score = 0.0

    supporting = []
    contradicting = []

    maximum_positive = sum(
        definition[
            "supports"
        ].values()
    )

    for feature, weight in (
        definition[
            "supports"
        ].items()
    ):
        if features.get(feature):
            score += weight

            supporting.append(
                {
                    "signal":
                        feature,

                    "weight":
                        weight,
                }
            )

    for feature, penalty in (
        definition[
            "contradicts"
        ].items()
    ):
        if features.get(feature):
            score -= penalty

            contradicting.append(
                {
                    "signal":
                        feature,

                    "penalty":
                        penalty,
                }
            )

    score = max(
        0.0,
        score,
    )

    confidence = (
        score
        / maximum_positive
        if maximum_positive
        else 0
    )

    confidence = max(
        0.0,
        min(
            1.0,
            confidence,
        ),
    )

    return {
        "hypothesis":
            name,

        "title":
            definition["title"],

        "root_cause":
            definition["root_cause"],

        "raw_score":
            round(
                score,
                2,
            ),

        "confidence":
            round(
                confidence,
                4,
            ),

        "supporting_evidence":
            supporting,

        "contradicting_evidence":
            contradicting,

        "recommended_action":
            definition[
                "recommended_action"
            ],
    }


def investigate(evidence):
    features = detect_features(
        evidence
    )

    hypotheses = []

    for name, definition in (
        HYPOTHESES.items()
    ):
        hypotheses.append(
            score_hypothesis(
                name,
                definition,
                features,
            )
        )

    hypotheses.sort(
        key=lambda item:
            (
                item[
                    "confidence"
                ],
                item[
                    "raw_score"
                ],
            ),
        reverse=True,
    )

    for index, hypothesis in enumerate(
        hypotheses,
        start=1,
    ):
        hypothesis[
            "rank"
        ] = index

    top = hypotheses[0]

    margin = 0.0

    if len(hypotheses) > 1:
        margin = (
            top["confidence"]
            - hypotheses[1][
                "confidence"
            ]
        )

    return {
        "features":
            features,

        "hypotheses":
            hypotheses,

        "top_hypothesis":
            top,

        "confidence_margin":
            round(
                margin,
                4,
            ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Project 12 multi-hypothesis "
            "incident investigation agent"
        )
    )

    parser.add_argument(
        "--evidence",
        required=True,
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    args = parser.parse_args()

    evidence_path = Path(
        args.evidence
    )

    evidence = json.loads(
        evidence_path.read_text()
    )

    result = investigate(
        evidence
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    if args.output:

        output = Path(
            args.output
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                result,
                indent=2,
            )
        )

        print()
        print(
            f"HYPOTHESES_WRITTEN={output}"
        )

    print()
    print(
        "HYPOTHESIS_AGENT=PASS"
    )


if __name__ == "__main__":
    main()
