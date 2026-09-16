#!/usr/bin/env python3

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "incidents" / "incident_memory.db"
RESULTS_DIR = ROOT / "results" / "incidents"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def latest_incident_file():
    files = sorted(
        RESULTS_DIR.glob("INC-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise RuntimeError("No scenario incident files found")
    return files[0]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            scenario TEXT,
            severity TEXT,
            expected_root_cause TEXT,
            ai_root_cause TEXT,
            ai_classification TEXT,
            ai_confidence REAL,
            causal_root TEXT,
            hypothesis_root TEXT,
            hypothesis_confidence REAL,
            latency_peak REAL,
            error_rate_peak REAL,
            consumer_lag_peak REAL,
            queue_depth_peak REAL,
            database_latency_peak REAL,
            tls_failure_delta REAL,
            authentication_failure_delta REAL,
            retry_delta REAL,
            gc_delta REAL,
            heap_peak_bytes REAL,
            recovery_status TEXT,
            remediation TEXT,
            remediation_success INTEGER,
            operator_feedback TEXT,
            raw_record TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS remediation_stats (
            root_cause TEXT NOT NULL,
            remediation TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (root_cause, remediation)
        )
        """
    )
    connection.commit()


def metric(telemetry, name, field):
    value = telemetry.get("metrics", {}).get(name, {}).get(field)
    return 0.0 if value is None else float(value)


def choose_diagnosis(llm, fusion):
    if llm.get("root_cause"):
        return {
            "root_cause": llm.get("root_cause"),
            "classification": llm.get("incident_classification") or "local_llm",
            "confidence": float(llm.get("confidence", 0) or 0),
        }
    return {
        "root_cause": fusion.get("final_root_cause"),
        "classification": "deterministic_fusion",
        "confidence": float(fusion.get("final_confidence", 0) or 0),
    }


def build_record(scenario, telemetry, hypotheses, causal, llm, fusion, remediation, history):
    incident_id = scenario.get("incident_id")
    if not incident_id:
        raise RuntimeError("Scenario evidence has no incident_id")

    top_hypothesis = hypotheses.get("top_hypothesis", {})
    diagnosis = choose_diagnosis(llm, fusion)

    remediation_action = remediation.get("action") or ""
    remediation_executed = remediation.get("executed") is True
    verified = remediation.get("verification", {}).get("recovered") is True
    remediation_status = remediation.get("status")

    if remediation_status == "RECOVERED" and verified:
        recovery_status = "recovered"
    elif remediation_status == "BLOCKED_BY_SAFETY":
        recovery_status = "blocked_by_safety"
    elif remediation_status == "VERIFICATION_FAILED":
        recovery_status = "verification_failed"
    elif remediation_status == "UNSUPPORTED_ACTION":
        recovery_status = "unsupported_action"
    else:
        recovery_status = "not_recovered"

    if remediation_executed:
        remediation_success = 1 if verified else 0
    else:
        remediation_success = None

    record = {
        "incident_id": incident_id,
        "created_at": utc_now(),
        "scenario": scenario.get("scenario"),
        "severity": scenario.get("severity"),
        "expected_root_cause": scenario.get("expected_root_cause"),
        "ai_root_cause": diagnosis["root_cause"],
        "ai_classification": diagnosis["classification"],
        "ai_confidence": diagnosis["confidence"],
        "causal_root": causal.get("causal_root_signal"),
        "hypothesis_root": top_hypothesis.get("hypothesis"),
        "hypothesis_confidence": float(top_hypothesis.get("confidence", 0) or 0),
        "latency_peak": metric(telemetry, "latency_ms", "peak"),
        "error_rate_peak": metric(telemetry, "error_rate", "peak"),
        "consumer_lag_peak": metric(telemetry, "consumer_lag", "peak"),
        "queue_depth_peak": metric(telemetry, "queue_depth", "peak"),
        "database_latency_peak": metric(telemetry, "database_latency_ms", "peak"),
        "tls_failure_delta": metric(telemetry, "tls_failures", "delta"),
        "authentication_failure_delta": metric(telemetry, "authentication_failures", "delta"),
        "retry_delta": metric(telemetry, "retry_count", "delta"),
        "gc_delta": metric(telemetry, "young_gc_count", "delta"),
        "heap_peak_bytes": metric(telemetry, "heap_used_bytes", "peak"),
        "recovery_status": recovery_status,
        "remediation": remediation_action,
        "remediation_success": remediation_success,
        "operator_feedback": None,
    }

    record["raw_record"] = json.dumps(
        {
            "scenario": scenario,
            "telemetry": telemetry,
            "hypotheses": hypotheses,
            "causal": causal,
            "history": history,
            "fusion": fusion,
            "llm": llm,
            "remediation": remediation,
        }
    )
    return record


def store_record(connection, record):
    columns = list(record.keys())
    placeholders = ",".join(["?"] * len(columns))
    sql = (
        "INSERT OR REPLACE INTO incidents "
        f"({','.join(columns)}) VALUES ({placeholders})"
    )
    connection.execute(sql, [record[column] for column in columns])
    connection.commit()


def list_incidents(connection):
    rows = connection.execute(
        """
        SELECT
            incident_id,
            created_at,
            scenario,
            expected_root_cause,
            ai_root_cause,
            ai_confidence,
            causal_root,
            recovery_status,
            remediation,
            remediation_success,
            operator_feedback
        FROM incidents
        ORDER BY created_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def command_learn(args):
    scenario_path = Path(args.scenario) if args.scenario else latest_incident_file()
    scenario = load_json(scenario_path)
    telemetry = load_json(args.telemetry)
    hypotheses = load_json(args.hypotheses)
    causal = load_json(args.causal)
    llm = load_json(args.llm) if args.llm else {}
    fusion = load_json(args.fusion) if args.fusion else {}
    remediation = load_json(args.remediation) if args.remediation else {}
    history = load_json(args.history) if args.history else {}

    record = build_record(
        scenario,
        telemetry,
        hypotheses,
        causal,
        llm,
        fusion,
        remediation,
        history,
    )

    connection = connect()
    initialize(connection)
    store_record(connection, record)
    connection.close()

    print(f"INCIDENT_ID={record['incident_id']}")
    print(f"EXPECTED_ROOT_CAUSE={record['expected_root_cause']}")
    print(f"AI_ROOT_CAUSE={record['ai_root_cause']}")
    print(f"CAUSAL_ROOT={record['causal_root']}")
    print(f"AI_CONFIDENCE={record['ai_confidence']}")
    print(f"RECOVERY={record['recovery_status']}")
    print(f"REMEDIATION={record['remediation']}")
    print(f"REMEDIATION_SUCCESS={record['remediation_success']}")
    print(f"MEMORY_DB={DB_PATH}")
    print("INCIDENT_LEARNING=PASS")


def command_list():
    connection = connect()
    initialize(connection)
    incidents = list_incidents(connection)
    connection.close()
    print(json.dumps(incidents, indent=2))
    print()
    print(f"INCIDENT_COUNT={len(incidents)}")


def normalize_root_cause(value):
    if not value:
        return None
    aliases = {
        "tls_failure": "tls_failure",
        "tls_handshake_failure": "tls_failure",
        "authentication_failure": "authentication_failure",
        "authentication_service_failure": "authentication_failure",
        "auth_failure": "authentication_failure",
        "database_latency": "database_latency",
        "downstream_database_latency": "database_latency",
        "db_latency": "database_latency",
        "retry_storm": "retry_storm",
        "uncontrolled_retry_amplification": "retry_storm",
        "consumer_slowdown": "consumer_lag",
        "consumer_lag": "consumer_lag",
        "consumer_processing_degradation": "consumer_lag",
        "jvm_memory_pressure": "memory_pressure",
        "memory_pressure": "memory_pressure",
        "sustained_heap_growth": "memory_pressure",
        "gc_storm": "gc_storm",
        "excessive_allocation_rate": "gc_storm",
    }
    return aliases.get(value, value)


def command_stats():
    connection = connect()
    initialize(connection)
    rows = connection.execute(
        "SELECT expected_root_cause, ai_root_cause, scenario, recovery_status FROM incidents"
    ).fetchall()
    connection.close()

    total = len(rows)
    correct = 0
    recovered = 0
    for row in rows:
        expected = normalize_root_cause(row["expected_root_cause"])
        predicted = normalize_root_cause(row["ai_root_cause"])
        scenario = normalize_root_cause(row["scenario"])
        if predicted and (predicted == expected or predicted == scenario):
            correct += 1
        if row["recovery_status"] == "recovered":
            recovered += 1

    accuracy = correct / total if total else 0
    print(
        json.dumps(
            {
                "incident_count": total,
                "ai_root_cause_matches": correct,
                "ai_accuracy": round(accuracy, 4),
                "recovered_incidents": recovered,
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Project 12 incident learning and memory agent"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    learn_parser = subparsers.add_parser("learn")
    learn_parser.add_argument("--scenario", default=None)
    learn_parser.add_argument("--telemetry", default="results/incidents/latest-telemetry.json")
    learn_parser.add_argument("--hypotheses", default="results/incidents/latest-hypotheses.json")
    learn_parser.add_argument("--causal", default="results/incidents/latest-causal-analysis.json")
    learn_parser.add_argument("--history", default="results/incidents/latest-history.json")
    learn_parser.add_argument("--fusion", default="results/incidents/latest-fusion.json")
    learn_parser.add_argument("--llm", default=None)
    learn_parser.add_argument("--remediation", default="results/incidents/latest-remediation.json")

    subparsers.add_parser("list")
    subparsers.add_parser("stats")

    args = parser.parse_args()
    if args.command == "learn":
        command_learn(args)
    elif args.command == "list":
        command_list()
    elif args.command == "stats":
        command_stats()


if __name__ == "__main__":
    main()
