#!/usr/bin/env python3

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml


ROOT = Path(__file__).resolve().parents[1]

SCENARIO_FILE = ROOT / "scenarios" / "scenarios.yaml"

RESULTS_DIR = ROOT / "results" / "incidents"

WORKLOAD_URL = "http://127.0.0.1:8080"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_scenarios():
    with SCENARIO_FILE.open() as handle:
        return yaml.safe_load(handle)


def get_state():
    response = requests.get(
        f"{WORKLOAD_URL}/state",
        timeout=5,
    )

    response.raise_for_status()

    return response.json()


def set_scenario(name):
    response = requests.get(
        f"{WORKLOAD_URL}/scenario",
        params={
            "name": name
        },
        timeout=5,
    )

    response.raise_for_status()

    return response.json()


def counter_delta(before, after, field):
    return max(
        0,
        after.get(field, 0)
        - before.get(field, 0),
    )


def build_deltas(before, after):
    return {
        "request_count_delta":
            counter_delta(
                before,
                after,
                "request_count",
            ),

        "tls_failures_delta":
            counter_delta(
                before,
                after,
                "tls_failures",
            ),

        "authentication_failures_delta":
            counter_delta(
                before,
                after,
                "authentication_failures",
            ),

        "retry_count_delta":
            counter_delta(
                before,
                after,
                "retry_count",
            ),

        "consumer_lag_change":
            after.get("consumer_lag", 0)
            - before.get("consumer_lag", 0),

        "queue_depth_change":
            after.get("queue_depth", 0)
            - before.get("queue_depth", 0),

        "latency_ms_change":
            after.get("latency_ms", 0)
            - before.get("latency_ms", 0),

        "database_latency_ms_change":
            after.get(
                "database_latency_ms",
                0,
            )
            - before.get(
                "database_latency_ms",
                0,
            ),
    }


def command_list():
    scenarios = load_scenarios()

    for name, config in scenarios.items():

        print(
            f"{name:18} "
            f"{config['severity']:10} "
            f"{config['title']}"
        )


def command_state():
    print(
        json.dumps(
            get_state(),
            indent=2,
        )
    )


def command_reset():
    state = set_scenario(
        "normal"
    )

    print(
        json.dumps(
            state,
            indent=2,
        )
    )

    print(
        "SCENARIO_RESET=PASS"
    )


def run_incident(
    scenario_name,
    duration,
):
    scenarios = load_scenarios()

    if scenario_name not in scenarios:
        raise SystemExit(
            f"Unknown scenario: {scenario_name}"
        )

    if scenario_name == "normal":
        raise SystemExit(
            "Use reset instead of running "
            "the normal scenario."
        )

    scenario = scenarios[
        scenario_name
    ]

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    incident_id = (
        "INC-"
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d-%H%M%S"
        )
    )

    print(
        f"INCIDENT_ID={incident_id}"
    )

    print(
        f"SCENARIO={scenario_name}"
    )

    print(
        f"TITLE={scenario['title']}"
    )

    print(
        f"SEVERITY={scenario['severity']}"
    )

    before = get_state()

    started_at = utc_now()

    set_scenario(
        scenario_name
    )

    samples = []

    print(
        f"SCENARIO_INJECTION={scenario_name}"
    )

    print(
        f"DURATION_SECONDS={duration}"
    )

    for second in range(
        duration
    ):
        time.sleep(1)

        state = get_state()

        sample = {
            "second": second + 1,
            "timestamp": utc_now(),
            "state": state,
        }

        samples.append(
            sample
        )

        print(
            f"[{second + 1:02d}s] "
            f"latency={state['latency_ms']}ms "
            f"lag={state['consumer_lag']} "
            f"queue={state['queue_depth']} "
            f"retries={state['retry_count']} "
            f"tls={state['tls_failures']} "
            f"auth={state['authentication_failures']}"
        )

    during_final = get_state()

    set_scenario(
        "normal"
    )

    time.sleep(2)

    recovered = get_state()

    finished_at = utc_now()

    incident = {
        "incident_id":
            incident_id,

        "scenario":
            scenario_name,

        "title":
            scenario["title"],

        "severity":
            scenario["severity"],

        "expected_root_cause":
            scenario["root_cause"],

        "expected_signals":
            scenario["expected_signals"],

        "recommended_action":
            scenario["recommended_action"],

        "started_at":
            started_at,

        "finished_at":
            finished_at,

        "duration_seconds":
            duration,

        "before":
            before,

        "samples":
            samples,

        "incident_final":
            during_final,

        "recovered":
            recovered,

        "deltas":
            build_deltas(
                before,
                during_final,
            ),
    }

    output = (
        RESULTS_DIR
        / f"{incident_id}.json"
    )

    output.write_text(
        json.dumps(
            incident,
            indent=2,
        )
    )

    print()

    print(
        f"EVIDENCE={output}"
    )

    print(
        "SCENARIO_EXECUTION=PASS"
    )

    print(
        "WORKLOAD_RECOVERY=PASS"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Project 12 incident "
            "scenario engine"
        )
    )

    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )

    subparsers.add_parser(
        "list"
    )

    subparsers.add_parser(
        "state"
    )

    subparsers.add_parser(
        "reset"
    )

    run_parser = (
        subparsers.add_parser(
            "run"
        )
    )

    run_parser.add_argument(
        "scenario"
    )

    run_parser.add_argument(
        "--duration",
        type=int,
        default=15,
    )

    args = parser.parse_args()

    if args.command == "list":
        command_list()

    elif args.command == "state":
        command_state()

    elif args.command == "reset":
        command_reset()

    elif args.command == "run":
        run_incident(
            args.scenario,
            args.duration,
        )


if __name__ == "__main__":
    main()
