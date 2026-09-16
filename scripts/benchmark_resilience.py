#!/usr/bin/env python3

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "results" / "benchmarks"
INCIDENT_DIR = ROOT / "results" / "incidents"
WORKLOAD_URL = "http://127.0.0.1:8080"

RESULT_DIR.mkdir(parents=True, exist_ok=True)
INCIDENT_DIR.mkdir(parents=True, exist_ok=True)

SCENARIOS = {
    "tls_failure": {
        "expected_root": "tls_failure",
        "settle_seconds": 15,
    },
    "auth_failure": {
        "expected_root": "authentication_failure",
        "settle_seconds": 15,
    },
    "db_latency": {
        "expected_root": "database_latency",
        "settle_seconds": 15,
    },
    "retry_storm": {
        "expected_root": "retry_storm",
        "settle_seconds": 15,
    },
    "consumer_lag": {
        "expected_root": "consumer_slowdown",
        "settle_seconds": 15,
    },
    "gc_storm": {
        "expected_root": "gc_storm",
        "settle_seconds": 25,
    },
    "memory_pressure": {
        "expected_root": "jvm_memory_pressure",
        "settle_seconds": 100,
    },
}

BASELINE_WAIT_SECONDS = 20
REMEDIATION_WAIT_SECONDS = 10


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def workload_state():
    response = requests.get(
        f"{WORKLOAD_URL}/state",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def set_scenario(name):
    response = requests.get(
        f"{WORKLOAD_URL}/scenario",
        params={"name": name},
        timeout=10,
    )
    response.raise_for_status()
    return response.text


def run_agent(arguments, timeout=300):
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started

    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(arguments)
            + "\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr
        )

    return elapsed


def load_incident(name):
    path = INCIDENT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Expected incident artifact not found: {path}")
    return json.loads(path.read_text())



def write_learning_scenario(scenario, expected, remediation):
    incident_id = f"INC-BENCH-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "incident_id": incident_id,
        "scenario": scenario,
        "severity": "benchmark",
        "expected_root_cause": expected,
        "recovered": remediation.get("after", {}),
        "created_at": utc_now(),
    }
    path = INCIDENT_DIR / f"{incident_id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return incident_id, path


def learn_incident(scenario, expected, with_llm, remediation):
    incident_id, scenario_path = write_learning_scenario(
        scenario,
        expected,
        remediation,
    )

    command = [
        "agents/memory_agent.py",
        "learn",
        "--scenario",
        str(scenario_path.relative_to(ROOT)),
        "--telemetry",
        "results/incidents/latest-telemetry.json",
        "--hypotheses",
        "results/incidents/latest-hypotheses.json",
        "--causal",
        "results/incidents/latest-causal-analysis.json",
        "--history",
        "results/incidents/latest-history.json",
        "--fusion",
        "results/incidents/latest-fusion.json",
        "--remediation",
        "results/incidents/latest-remediation.json",
    ]

    if with_llm:
        command.extend([
            "--llm",
            "results/incidents/latest-llm-investigation.json",
        ])

    run_agent(command)

    outcome_learning = "NOT_APPLICABLE"
    if remediation.get("executed") is True:
        run_agent(["agents/outcome_agent.py"])
        outcome_learning = "PASS"

    return incident_id, outcome_learning


def wait_for_normal(timeout=30):
    deadline = time.time() + timeout
    last = {}

    while time.time() < deadline:
        last = workload_state()
        if (
            last.get("scenario") == "normal"
            and float(last.get("latency_ms", 999999)) <= 250
            and float(last.get("error_rate", 1)) <= 0.01
            and float(last.get("queue_depth", 999999)) <= 20
            and float(last.get("database_latency_ms", 999999)) <= 100
        ):
            return last
        time.sleep(1)

    raise RuntimeError(
        f"Workload failed to reach healthy normal state: {last}"
    )


def run_one(scenario, config, with_llm):
    expected = config["expected_root"]
    settle = config["settle_seconds"]

    # Keep the evidence window narrow enough to avoid contamination
    # from the previous scenario while still covering fault onset.
    evidence_window_seconds = settle + 5

    row = {
        "scenario": scenario,
        "expected_root_cause": expected,
        "started_at": utc_now(),
    }

    benchmark_start = time.perf_counter()

    try:
        set_scenario("normal")
        wait_for_normal()
        time.sleep(BASELINE_WAIT_SECONDS)

        baseline = workload_state()
        row.update(
            {
                "baseline_scenario": baseline.get("scenario"),
                "baseline_latency_ms": baseline.get("latency_ms"),
                "baseline_consumer_lag": baseline.get("consumer_lag"),
                "baseline_queue_depth": baseline.get("queue_depth"),
            }
        )

        injection_start = time.perf_counter()
        set_scenario(scenario)
        time.sleep(settle)

        active = workload_state()
        row.update(
            {
                "active_scenario": active.get("scenario"),
                "active_latency_ms": active.get("latency_ms"),
                "active_error_rate": active.get("error_rate"),
                "active_consumer_lag": active.get("consumer_lag"),
                "active_queue_depth": active.get("queue_depth"),
                "active_database_latency_ms": active.get(
                    "database_latency_ms"
                ),
            }
        )

        diagnosis_start = time.perf_counter()

        run_agent(
            [
                "agents/telemetry_agent.py",
                "--window",
                f"{evidence_window_seconds}s",
                "--output",
                "results/incidents/latest-telemetry.json",
            ]
        )
        row["detection_seconds"] = round(
            time.perf_counter() - injection_start,
            3,
        )

        run_agent(
            [
                "agents/hypothesis_agent.py",
                "--evidence",
                "results/incidents/latest-telemetry.json",
                "--output",
                "results/incidents/latest-hypotheses.json",
            ]
        )

        run_agent(
            [
                "agents/causal_agent.py",
                "--window",
                f"{evidence_window_seconds}s",
                "--hypotheses",
                "results/incidents/latest-hypotheses.json",
                "--output",
                "results/incidents/latest-causal-analysis.json",
            ]
        )

        run_agent(
            [
                "agents/history_agent.py",
                "--telemetry",
                "results/incidents/latest-telemetry.json",
                "--top-k",
                "5",
            ]
        )

        run_agent(["agents/fusion_agent.py"])
        run_agent(["agents/safety_agent.py"])

        if with_llm:
            run_agent(
                ["agents/llm_investigator.py"],
                timeout=360,
            )

        row["diagnosis_seconds"] = round(
            time.perf_counter() - diagnosis_start,
            3,
        )

        hypotheses = load_incident("latest-hypotheses.json")
        causal = load_incident("latest-causal-analysis.json")
        fusion = load_incident("latest-fusion.json")
        safety = load_incident("latest-safety.json")

        detected = fusion.get("final_root_cause")

        row.update(
            {
                "top_live_hypothesis": hypotheses.get(
                    "top_hypothesis", {}
                ).get("hypothesis"),
                "raw_causal_root": causal.get("causal_root_signal"),
                "detected_root_cause": detected,
                "diagnosis_correct": detected == expected,
                "fused_confidence": fusion.get("final_confidence"),
                "memory_gate": fusion.get("memory_gate_status"),
                "historical_matches_used": fusion.get(
                    "historical_matches_used"
                ),
                "safety_decision": safety.get("decision"),
                "remediation_action": safety.get("action"),
                "remediation_risk": safety.get("risk"),
            }
        )

        if with_llm:
            llm = load_incident("latest-llm-investigation.json")
            row["llm_root_cause"] = llm.get("root_cause")
            row["llm_confidence"] = llm.get("confidence")

        remediation_start = time.perf_counter()
        run_agent(
            [
                "agents/remediation_agent.py",
                "--wait",
                str(REMEDIATION_WAIT_SECONDS),
            ]
        )
        row["remediation_seconds"] = round(
            time.perf_counter() - remediation_start,
            3,
        )

        remediation = load_incident("latest-remediation.json")
        row.update(
            {
                "remediation_executed": remediation.get("executed"),
                "remediation_status": remediation.get("status"),
                "before_remediation_scenario": remediation.get(
                    "before", {}
                ).get("scenario"),
                "after_remediation_scenario": remediation.get(
                    "after", {}
                ).get("scenario"),
                "recovery_verified": remediation.get(
                    "verification", {}
                ).get("recovered", False),
                "total_recovery_seconds": round(
                    time.perf_counter() - injection_start,
                    3,
                ),
            }
        )

        final = workload_state()
        row.update(
            {
                "final_scenario": final.get("scenario"),
                "final_latency_ms": final.get("latency_ms"),
                "final_consumer_lag": final.get("consumer_lag"),
                "final_queue_depth": final.get("queue_depth"),
            }
        )

        row["benchmark_status"] = (
            "PASS"
            if (
                row["diagnosis_correct"]
                and row["safety_decision"] == "AUTO_EXECUTE"
                and row["remediation_executed"] is True
                and row["recovery_verified"] is True
                and row["before_remediation_scenario"] == scenario
                and row["after_remediation_scenario"] == "normal"
                and row["final_scenario"] == "normal"
            )
            else "FAIL"
        )

        # Persist every investigated incident, including incidents that were
        # blocked by safety or failed recovery verification.  This keeps the
        # long-term learning corpus complete.  Remediation outcome statistics
        # are updated only when an action was actually executed.
        learning_start = time.perf_counter()
        learned_incident_id, outcome_learning = learn_incident(
            scenario,
            expected,
            with_llm,
            remediation,
        )
        row["learned_incident_id"] = learned_incident_id
        row["learning_seconds"] = round(
            time.perf_counter() - learning_start,
            3,
        )
        row["incident_learning"] = "PASS"
        row["outcome_learning"] = outcome_learning

    except Exception as exc:
        row["benchmark_status"] = "ERROR"
        row["error"] = str(exc)

    finally:
        try:
            set_scenario("normal")
            wait_for_normal()
        except Exception as cleanup_exc:
            row["cleanup_error"] = str(cleanup_exc)

        row["completed_at"] = utc_now()
        row["benchmark_elapsed_seconds"] = round(
            time.perf_counter() - benchmark_start,
            3,
        )

    return row


def write_csv(rows, path):
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows, path):
    total = len(rows)
    passed = sum(
        row.get("benchmark_status") == "PASS"
        for row in rows
    )
    correct = sum(
        row.get("diagnosis_correct") is True
        for row in rows
    )
    recovered = sum(
        row.get("recovery_verified") is True
        for row in rows
    )

    recovery_times = [
        row["total_recovery_seconds"]
        for row in rows
        if isinstance(row.get("total_recovery_seconds"), (int, float))
    ]

    median_recovery = (
        statistics.median(recovery_times)
        if recovery_times
        else None
    )

    lines = [
        "# Project 12 Autonomous Resilience Benchmark",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Summary",
        "",
        f"- Scenarios tested: {total}",
        f"- End-to-end passes: {passed}/{total}",
        f"- Correct root-cause diagnoses: {correct}/{total}",
        f"- Verified recoveries: {recovered}/{total}",
        (
            "- Median total time from injection to verified recovery: "
            + (
                f"{median_recovery:.3f} seconds"
                if median_recovery is not None
                else "N/A"
            )
        ),
        "",
        "## Results",
        "",
        (
            "| Scenario | Expected | Detected | Confidence | "
            "Safety | Recovery | Status |"
        ),
        "|---|---|---|---:|---|---|---|",
    ]

    for row in rows:
        lines.append(
            "| "
            + str(row.get("scenario", ""))
            + " | "
            + str(row.get("expected_root_cause", ""))
            + " | "
            + str(row.get("detected_root_cause", ""))
            + " | "
            + str(row.get("fused_confidence", ""))
            + " | "
            + str(row.get("safety_decision", ""))
            + " | "
            + str(row.get("recovery_verified", ""))
            + " | "
            + str(row.get("benchmark_status", ""))
            + " |"
        )

    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Project 12 autonomous resilience benchmark"
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also run the local Ollama investigator for every scenario.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=list(SCENARIOS),
        help=(
            "Run only the selected scenario. "
            "May be specified multiple times."
        ),
    )
    args = parser.parse_args()

    selected = args.scenario if args.scenario else list(SCENARIOS)
    rows = []

    print("PROJECT12_BENCHMARK=START")
    print(f"SCENARIOS={len(selected)}")
    print(f"WITH_LLM={args.with_llm}")
    print()

    for index, scenario in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {scenario}", flush=True)

        row = run_one(
            scenario,
            SCENARIOS[scenario],
            args.with_llm,
        )
        rows.append(row)

        print(f"  expected={row.get('expected_root_cause')}")
        print(f"  detected={row.get('detected_root_cause')}")
        print(f"  confidence={row.get('fused_confidence')}")
        print(f"  safety={row.get('safety_decision')}")
        print(f"  recovery={row.get('recovery_verified')}")
        print(f"  status={row.get('benchmark_status')}")

        if row.get("error"):
            print(f"  error={row['error']}")
        if row.get("cleanup_error"):
            print(f"  cleanup_error={row['cleanup_error']}")
        print(flush=True)

    json_path = RESULT_DIR / "autonomous_resilience_benchmark.json"
    csv_path = RESULT_DIR / "autonomous_resilience_benchmark.csv"
    summary_path = RESULT_DIR / "benchmark_summary.md"

    json_path.write_text(json.dumps(rows, indent=2) + "\n")
    write_csv(rows, csv_path)
    write_summary(rows, summary_path)

    passed = sum(
        row.get("benchmark_status") == "PASS"
        for row in rows
    )

    print(f"BENCHMARK_PASS={passed}/{len(rows)}")
    print(f"JSON={json_path}")
    print(f"CSV={csv_path}")
    print(f"SUMMARY={summary_path}")

    return 0 if passed == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
