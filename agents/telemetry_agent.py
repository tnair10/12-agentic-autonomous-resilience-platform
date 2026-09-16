#!/usr/bin/env python3

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


PROMETHEUS = "http://127.0.0.1:9090"

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_DIR = ROOT / "results" / "incidents"


METRICS = {
    "latency_ms": {
        "current":
            "com_project12_workloadmetrics_latencyms",

        "peak":
            "max_over_time("
            "com_project12_workloadmetrics_latencyms[{window}])",
    },

    "error_rate": {
        "current":
            "com_project12_workloadmetrics_errorrate",

        "peak":
            "max_over_time("
            "com_project12_workloadmetrics_errorrate[{window}])",
    },

    "consumer_lag": {
        "current":
            "com_project12_workloadmetrics_consumerlag",

        "peak":
            "max_over_time("
            "com_project12_workloadmetrics_consumerlag[{window}])",
    },

    "queue_depth": {
        "current":
            "com_project12_workloadmetrics_queuedepth",

        "peak":
            "max_over_time("
            "com_project12_workloadmetrics_queuedepth[{window}])",
    },

    "database_latency_ms": {
        "current":
            "com_project12_workloadmetrics_databaselatencyms",

        "peak":
            "max_over_time("
            "com_project12_workloadmetrics_databaselatencyms[{window}])",
    },

    "tls_failures": {
        "current":
            "com_project12_workloadmetrics_tlsfailures",

        "delta":
            "max_over_time("
            "com_project12_workloadmetrics_tlsfailures[{window}])"
            " - "
            "min_over_time("
            "com_project12_workloadmetrics_tlsfailures[{window}])",
    },

    "authentication_failures": {
        "current":
            "com_project12_workloadmetrics_authenticationfailures",

        "delta":
            "max_over_time("
            "com_project12_workloadmetrics_authenticationfailures[{window}])"
            " - "
            "min_over_time("
            "com_project12_workloadmetrics_authenticationfailures[{window}])",
    },

    "retry_count": {
        "current":
            "com_project12_workloadmetrics_retrycount",

        "delta":
            "max_over_time("
            "com_project12_workloadmetrics_retrycount[{window}])"
            " - "
            "min_over_time("
            "com_project12_workloadmetrics_retrycount[{window}])",
    },

    "heap_used_bytes": {
        "current":
            "java_lang_memory_heapmemoryusage_used",

        "peak":
            "max_over_time("
            "java_lang_memory_heapmemoryusage_used[{window}])",
    },

    "heap_max_bytes": {
        "current":
            "java_lang_memory_heapmemoryusage_max",
    },

    "young_gc_count": {
        "current":
            "java_lang_g1_young_generation_collectioncount",

        "delta":
            "max_over_time("
            "java_lang_g1_young_generation_collectioncount[{window}])"
            " - "
            "min_over_time("
            "java_lang_g1_young_generation_collectioncount[{window}])",
    },
}


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def query_prometheus(expression):
    response = requests.get(
        f"{PROMETHEUS}/api/v1/query",
        params={
            "query": expression
        },
        timeout=10,
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("status") != "success":
        raise RuntimeError(
            f"Prometheus query failed: {payload}"
        )

    result = (
        payload
        .get("data", {})
        .get("result", [])
    )

    if not result:
        return None

    return float(
        result[0]["value"][1]
    )


def collect(window):
    evidence = {
        "collected_at":
            utc_now(),

        "window":
            window,

        "prometheus":
            PROMETHEUS,

        "target_up":
            query_prometheus(
                'up{job="project12-java-workload"}'
            ),

        "metrics": {},
    }

    for name, queries in METRICS.items():

        metric_data = {}

        for query_type, expression in queries.items():

            expression = expression.format(
                window=window
            )

            metric_data[
                query_type
            ] = query_prometheus(
                expression
            )

        evidence["metrics"][
            name
        ] = metric_data

    heap_used = (
        evidence["metrics"]
        ["heap_used_bytes"]
        .get("current")
    )

    heap_max = (
        evidence["metrics"]
        ["heap_max_bytes"]
        .get("current")
    )

    if (
        heap_used is not None
        and heap_max
        and heap_max > 0
    ):
        evidence[
            "derived"
        ] = {
            "heap_utilization_percent":
                (
                    heap_used
                    / heap_max
                    * 100
                )
        }

    else:
        evidence[
            "derived"
        ] = {
            "heap_utilization_percent":
                None
        }

    return evidence


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Project 12 telemetry "
            "evidence agent"
        )
    )

    parser.add_argument(
        "--window",
        default="5m",
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    args = parser.parse_args()

    evidence = collect(
        args.window
    )

    print(
        json.dumps(
            evidence,
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
                evidence,
                indent=2,
            )
        )

        print()
        print(
            f"EVIDENCE_WRITTEN={output}"
        )

    print()
    print(
        "TELEMETRY_AGENT=PASS"
    )


if __name__ == "__main__":
    main()
