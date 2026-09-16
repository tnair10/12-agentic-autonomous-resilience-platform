#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


WORKLOAD_URL = "http://127.0.0.1:8080"
PROMETHEUS_URL = "http://127.0.0.1:9090"
WORKLOAD_PID_FILE = Path("/tmp/project12-workload.pid")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    return json.loads(Path(path).read_text())


def workload_state():
    response = requests.get(
        f"{WORKLOAD_URL}/state",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def reset_workload():
    response = requests.get(
        f"{WORKLOAD_URL}/scenario",
        params={"name": "normal"},
        timeout=10,
    )
    response.raise_for_status()
    return response.text


def prometheus_value(query):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": query},
        timeout=10,
    )
    response.raise_for_status()

    payload = response.json()
    results = payload.get("data", {}).get("result", [])

    if not results:
        return None

    return float(results[0]["value"][1])


def force_local_gc():
    if not WORKLOAD_PID_FILE.exists():
        raise RuntimeError(
            f"Java workload PID file missing: {WORKLOAD_PID_FILE}"
        )

    jcmd = shutil.which("jcmd")
    if not jcmd:
        raise RuntimeError("jcmd was not found in PATH")

    pid = WORKLOAD_PID_FILE.read_text().strip()

    completed = subprocess.run(
        [jcmd, pid, "GC.run"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Local JVM GC failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )

    return {
        "pid": pid,
        "command": "jcmd <pid> GC.run",
        "status": "PASS",
        "stdout": completed.stdout.strip(),
    }


def verify_recovery(root_cause=None):
    metrics = {
        "target_up": prometheus_value(
            'up{job="project12-java-workload"}'
        ),
        "latency_ms": prometheus_value(
            "com_project12_workloadmetrics_latencyms"
        ),
        "error_rate": prometheus_value(
            "com_project12_workloadmetrics_errorrate"
        ),
        "consumer_lag": prometheus_value(
            "com_project12_workloadmetrics_consumerlag"
        ),
        "queue_depth": prometheus_value(
            "com_project12_workloadmetrics_queuedepth"
        ),
        "database_latency_ms": prometheus_value(
            "com_project12_workloadmetrics_databaselatencyms"
        ),
        "heap_used_bytes": prometheus_value(
            "java_lang_memory_heapmemoryusage_used"
        ),
        "heap_max_bytes": prometheus_value(
            "java_lang_memory_heapmemoryusage_max"
        ),
    }

    heap_used = metrics["heap_used_bytes"]
    heap_max = metrics["heap_max_bytes"]

    heap_percent = None
    if (
        heap_used is not None
        and heap_max is not None
        and heap_max > 0
    ):
        heap_percent = heap_used / heap_max * 100.0

    metrics["heap_utilization_percent"] = heap_percent

    checks = {
        "target_up": metrics["target_up"] == 1,
        "latency_recovered": (
            metrics["latency_ms"] is not None
            and metrics["latency_ms"] <= 250
        ),
        "error_rate_recovered": (
            metrics["error_rate"] is not None
            and metrics["error_rate"] <= 0.01
        ),
        "consumer_lag_recovered": (
            metrics["consumer_lag"] is not None
            and metrics["consumer_lag"] <= 100
        ),
        "queue_recovered": (
            metrics["queue_depth"] is not None
            and metrics["queue_depth"] <= 20
        ),
        "database_latency_recovered": (
            metrics["database_latency_ms"] is not None
            and metrics["database_latency_ms"] <= 100
        ),
    }

    if root_cause == "jvm_memory_pressure":
        checks["heap_recovered"] = (
            heap_percent is not None
            and heap_percent < 70
        )

    return {
        "metrics": metrics,
        "checks": checks,
        "recovered": all(checks.values()),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Project 12 autonomous remediation agent"
    )

    parser.add_argument(
        "--safety",
        default="results/incidents/latest-safety.json",
    )

    parser.add_argument(
        "--output",
        default="results/incidents/latest-remediation.json",
    )

    parser.add_argument(
        "--wait",
        type=int,
        default=8,
    )

    args = parser.parse_args()

    safety = load_json(args.safety)
    before = workload_state()

    result = {
        "started_at": utc_now(),
        "safety_decision": safety.get("decision"),
        "root_cause": safety.get("root_cause"),
        "action": safety.get("action"),
        "before": before,
        "executed": False,
    }

    if safety.get("decision") != "AUTO_EXECUTE":
        result["status"] = "BLOCKED_BY_SAFETY"

    elif safety.get("action") != "reset_workload":
        result["status"] = "UNSUPPORTED_ACTION"

    else:
        reset_workload()
        result["executed"] = True
        result["execution_time"] = utc_now()

        if result["root_cause"] == "jvm_memory_pressure":
            result["gc"] = force_local_gc()

        time.sleep(args.wait)

        result["after"] = workload_state()
        result["verification"] = verify_recovery(
            result["root_cause"]
        )

        result["status"] = (
            "RECOVERED"
            if result["verification"]["recovered"]
            else "VERIFICATION_FAILED"
        )

    result["completed_at"] = utc_now()

    Path(args.output).write_text(
        json.dumps(result, indent=2)
    )

    print(json.dumps(result, indent=2))
    print()
    print(f"REMEDIATION_WRITTEN={args.output}")
    print(f"REMEDIATION_STATUS={result['status']}")


if __name__ == "__main__":
    main()
