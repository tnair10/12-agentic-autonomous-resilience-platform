#!/usr/bin/env python3

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "incidents"
BENCHMARKS = ROOT / "results" / "benchmarks"
DB_PATH = ROOT / "data" / "incidents" / "incident_memory.db"
WORKLOAD_URL = "http://127.0.0.1:8080"
PROMETHEUS_URL = "http://127.0.0.1:9090"
UI_INCIDENT_LIMIT = 25

FILES = {
    "telemetry": RESULTS / "latest-telemetry.json",
    "hypotheses": RESULTS / "latest-hypotheses.json",
    "causal": RESULTS / "latest-causal-analysis.json",
    "history": RESULTS / "latest-history.json",
    "fusion": RESULTS / "latest-fusion.json",
    "safety": RESULTS / "latest-safety.json",
    "remediation": RESULTS / "latest-remediation.json",
    "llm": RESULTS / "latest-llm-investigation.json",
}

SCENARIOS = [
    "normal",
    "memory_pressure",
    "gc_storm",
    "consumer_lag",
    "tls_failure",
    "auth_failure",
    "db_latency",
    "retry_storm",
]


def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def workload_state():
    try:
        response = requests.get(
            f"{WORKLOAD_URL}/state",
            timeout=3,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def inject_scenario(name):
    response = requests.get(
        f"{WORKLOAD_URL}/scenario",
        params={"name": name},
        timeout=5,
    )
    response.raise_for_status()
    return response.text


def prometheus_value(query):
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()
        result = (
            response.json()
            .get("data", {})
            .get("result", [])
        )
        if not result:
            return None
        return float(result[0]["value"][1])
    except Exception:
        return None


def run_command(arguments, timeout=360):
    completed = subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_investigation(include_llm=True):
    commands = [
        [
            "agents/telemetry_agent.py",
            "--window",
            "90s",
            "--output",
            "results/incidents/latest-telemetry.json",
        ],
        [
            "agents/hypothesis_agent.py",
            "--evidence",
            "results/incidents/latest-telemetry.json",
            "--output",
            "results/incidents/latest-hypotheses.json",
        ],
        [
            "agents/causal_agent.py",
            "--window",
            "90s",
            "--hypotheses",
            "results/incidents/latest-hypotheses.json",
            "--output",
            "results/incidents/latest-causal-analysis.json",
        ],
        [
            "agents/history_agent.py",
            "--telemetry",
            "results/incidents/latest-telemetry.json",
            "--top-k",
            "5",
        ],
        ["agents/fusion_agent.py"],
        ["agents/safety_agent.py"],
    ]

    if include_llm:
        commands.append(["agents/llm_investigator.py"])

    results = []
    for command in commands:
        result = run_command(command)
        results.append(
            {
                "command": " ".join(command),
                **result,
            }
        )
        if result["returncode"] != 0:
            break

    return results


def execute_remediation():
    return run_command(
        [
            "agents/remediation_agent.py",
            "--wait",
            "10",
        ]
    )


def causal_dot(causal):
    links = causal.get("causal_links", [])
    root = causal.get("causal_root_signal")
    lines = [
        "digraph G {",
        'rankdir="LR";',
        'node [shape="box"];',
    ]

    nodes = set()
    for link in links:
        source = link.get("source")
        target = link.get("target")
        if source:
            nodes.add(source)
        if target:
            nodes.add(target)

    for node in sorted(nodes):
        safe = str(node).replace('"', '\\"')
        if node == root:
            lines.append(f'"{safe}" [shape="doubleoctagon"];')
        else:
            lines.append(f'"{safe}";')

    for link in links:
        source = link.get("source")
        target = link.get("target")
        if not source or not target:
            continue
        source_safe = str(source).replace('"', '\\"')
        target_safe = str(target).replace('"', '\\"')
        lines.append(f'"{source_safe}" -> "{target_safe}";')

    lines.append("}")
    return "\n".join(lines)


def incident_count():
    if not DB_PATH.exists():
        return 0

    try:
        with sqlite3.connect(DB_PATH) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM incidents"
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def incident_history(limit=UI_INCIDENT_LIMIT):
    if not DB_PATH.exists():
        return pd.DataFrame()

    try:
        with sqlite3.connect(DB_PATH) as connection:
            query = """
                SELECT
                    incident_id,
                    created_at,
                    scenario,
                    expected_root_cause,
                    ai_root_cause,
                    ai_confidence,
                    causal_root,
                    recovery_status
                FROM incidents
                ORDER BY created_at DESC
                LIMIT ?
            """
            return pd.read_sql_query(
                query,
                connection,
                params=(limit,),
            )
    except Exception:
        return pd.DataFrame()


def remediation_stats():
    if not DB_PATH.exists():
        return pd.DataFrame()

    try:
        connection = sqlite3.connect(DB_PATH)
        query = """
            SELECT
                root_cause,
                remediation,
                attempts,
                successes,
                failures,
                CASE
                    WHEN attempts > 0
                    THEN ROUND(CAST(successes AS REAL) / attempts, 4)
                    ELSE 0
                END AS success_rate
            FROM remediation_stats
            ORDER BY attempts DESC
        """
        df = pd.read_sql_query(query, connection)
        connection.close()
        return df
    except Exception:
        return pd.DataFrame()


def benchmark_dataframe():
    path = BENCHMARKS / "autonomous_resilience_benchmark.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


st.set_page_config(
    page_title="Project 12 | Autonomous Resilience Platform",
    page_icon="🧠",
    layout="wide",
)

st.title("Project 12 — Agentic Autonomous Resilience Platform")
st.caption(
    "Observe → Diagnose → Reason → Learn → Decide → Remediate → Verify"
)

state = workload_state()
target_up = prometheus_value('up{job="project12-java-workload"}')

col1, col2, col3, col4 = st.columns(4)
col1.metric("Workload Scenario", state.get("scenario", "unknown"))
col2.metric(
    "Prometheus Target",
    "UP" if target_up == 1 else "DOWN",
)
col3.metric(
    "Latency",
    f"{state.get('latency_ms')} ms"
    if "latency_ms" in state
    else "N/A",
)
col4.metric("Consumer Lag", state.get("consumer_lag", "N/A"))

tabs = st.tabs(
    [
        "Operations",
        "Investigation",
        "Causal Graph",
        "Memory",
        "Remediation",
        "Scenario Lab",
        "AI RCA",
        "Benchmark",
    ]
)

with tabs[0]:
    st.subheader("Live Workload")

    if "error" in state:
        st.error(state["error"])
    else:
        live = pd.DataFrame(
            [
                {"Metric": "Latency ms", "Value": state.get("latency_ms")},
                {"Metric": "Error rate", "Value": state.get("error_rate")},
                {"Metric": "Consumer lag", "Value": state.get("consumer_lag")},
                {"Metric": "Queue depth", "Value": state.get("queue_depth")},
                {
                    "Metric": "Database latency ms",
                    "Value": state.get("database_latency_ms"),
                },
                {"Metric": "TLS failures", "Value": state.get("tls_failures")},
                {
                    "Metric": "Authentication failures",
                    "Value": state.get("authentication_failures"),
                },
                {"Metric": "Retries", "Value": state.get("retry_count")},
            ]
        )
        st.dataframe(live, width="stretch", hide_index=True)

    st.info("Grafana observability dashboard: http://127.0.0.1:3000/")

with tabs[1]:
    st.subheader("Multi-Agent Investigation")
    include_llm = st.checkbox(
        "Include local Ollama investigator",
        value=True,
    )

    if st.button("Run Full Investigation", type="primary"):
        with st.spinner(
            "Running telemetry, hypothesis, causal, memory, fusion, safety "
            "and optional local LLM agents..."
        ):
            execution = run_investigation(include_llm=include_llm)

        failed = [
            item for item in execution if item["returncode"] != 0
        ]

        if failed:
            st.error("Investigation pipeline failed.")
            st.code(
                failed[0]["stderr"] or failed[0]["stdout"] or "No output"
            )
        else:
            st.success("Investigation completed.")
            st.rerun()

    hypotheses = load_json(FILES["hypotheses"])
    fusion = load_json(FILES["fusion"])
    safety = load_json(FILES["safety"])

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Top Live Hypothesis",
        hypotheses.get("top_hypothesis", {}).get("hypothesis", "N/A"),
    )
    c2.metric(
        "Final Fused Root",
        fusion.get("final_root_cause", "N/A"),
    )
    c3.metric(
        "Fused Confidence",
        f"{numeric(fusion.get('final_confidence')):.3f}",
    )

    st.write("Memory Gate:", fusion.get("memory_gate_status", "N/A"))
    st.write("Safety Decision:", safety.get("decision", "N/A"))

    rankings = fusion.get("rankings", [])
    if rankings:
        st.dataframe(
            pd.DataFrame(rankings),
            width="stretch",
            hide_index=True,
        )

with tabs[2]:
    st.subheader("Temporal / Causal Reasoning")
    causal = load_json(FILES["causal"])

    st.write(
        "Raw causal root:",
        causal.get("causal_root_signal", "N/A"),
    )
    st.write(
        "Hypothesis:",
        causal.get("top_hypothesis", "N/A"),
    )

    if causal.get("causal_links"):
        st.graphviz_chart(causal_dot(causal), width="stretch")

    timeline = causal.get("timeline", [])
    if timeline:
        st.dataframe(
            pd.DataFrame(timeline),
            width="stretch",
            hide_index=True,
        )

with tabs[3]:
    st.subheader("Historical Incident Memory")

    total_incidents = incident_count()
    history_df = incident_history()

    memory_col1, memory_col2 = st.columns(2)
    memory_col1.metric(
        "Total Learned Incidents",
        total_incidents,
    )
    memory_col2.metric(
        "Incidents Shown",
        min(total_incidents, UI_INCIDENT_LIMIT),
    )

    st.caption(
        "The UI shows only the newest "
        f"{UI_INCIDENT_LIMIT} incidents. "
        "The learning/history agent retains and scores the full "
        "incident database before selecting the most relevant matches."
    )

    if history_df.empty:
        st.info("No incidents stored yet.")
    else:
        st.dataframe(
            history_df,
            width="stretch",
            hide_index=True,
        )

    st.subheader("Learned Remediation Outcomes")
    remediation_df = remediation_stats()

    if remediation_df.empty:
        st.info("No remediation outcomes stored yet.")
    else:
        st.dataframe(remediation_df, width="stretch", hide_index=True)

with tabs[4]:
    st.subheader("Risk-Aware Remediation")
    safety = load_json(FILES["safety"])
    st.json(safety)

    if safety.get("decision") == "AUTO_EXECUTE":
        st.warning(
            "An allowlisted low-risk autonomous action is approved."
        )

        if st.button("Execute Approved Remediation", type="primary"):
            with st.spinner(
                "Executing remediation and verifying recovery..."
            ):
                result = execute_remediation()

            if result["returncode"] == 0:
                st.success("Remediation execution completed.")
                st.rerun()
            else:
                st.error("Remediation execution failed.")
                st.code(result["stderr"] or result["stdout"] or "No output")
    else:
        st.info("Autonomous execution is not currently approved.")

    remediation = load_json(FILES["remediation"])
    if remediation:
        st.subheader("Latest Remediation Result")
        st.json(remediation)

with tabs[5]:
    st.subheader("Failure Scenario Lab")
    selected = st.selectbox("Scenario", SCENARIOS)
    c1, c2 = st.columns(2)

    with c1:
        if st.button("Inject Scenario"):
            try:
                inject_scenario(selected)
                time.sleep(2)
                st.success(f"Injected: {selected}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with c2:
        if st.button("Reset to Normal"):
            try:
                inject_scenario("normal")
                time.sleep(2)
                st.success("Workload reset.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.json(workload_state())

with tabs[6]:
    st.subheader("Grounded Local LLM RCA")
    llm = load_json(FILES["llm"])

    if not llm:
        st.info("Run an investigation with the Ollama option enabled.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Root Cause", llm.get("root_cause", "N/A"))
        c2.metric("Confidence", llm.get("confidence", 0))

        st.subheader("Executive Summary")
        st.write(llm.get("executive_summary", ""))

        evidence = llm.get("evidence", [])
        if evidence:
            st.subheader("Evidence")
            for item in evidence:
                st.write(f"- {item}")

        actions = llm.get("recommended_actions", [])
        if actions:
            st.subheader("Recommended Actions")
            for item in actions:
                st.write(f"- {item}")

        with st.expander("Raw LLM result"):
            st.json(llm)

with tabs[7]:
    st.subheader("Autonomous Resilience Benchmark")

    summary_path = BENCHMARKS / "benchmark_summary.md"
    if summary_path.exists():
        st.markdown(summary_path.read_text())
    else:
        st.info(
            "No benchmark results yet. Run scripts/benchmark_resilience.py."
        )

    benchmark_df = benchmark_dataframe()
    if not benchmark_df.empty:
        st.dataframe(
            benchmark_df,
            width="stretch",
            hide_index=True,
        )
