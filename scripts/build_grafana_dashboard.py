#!/usr/bin/env python3

import json
from pathlib import Path


OUTPUT = Path(
    "monitoring/grafana/dashboards/project12-operations.json"
)

DATASOURCE = {
    "type": "prometheus",
    "uid": "project12-prometheus",
}


def stat_panel(
    panel_id,
    title,
    expression,
    x,
    y,
    unit="short",
):
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "gridPos": {
            "h": 4,
            "w": 6,
            "x": x,
            "y": y,
        },
        "datasource": DATASOURCE,
        "targets": [
            {
                "refId": "A",
                "expr": expression,
                "instant": True,
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": 1,
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {
                "values": False,
                "calcs": [
                    "lastNotNull"
                ],
                "fields": "",
            },
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
        },
    }


def time_series_panel(
    panel_id,
    title,
    expression,
    legend,
    x,
    y,
    unit="short",
):
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "gridPos": {
            "h": 8,
            "w": 12,
            "x": x,
            "y": y,
        },
        "datasource": DATASOURCE,
        "targets": [
            {
                "refId": "A",
                "expr": expression,
                "legendFormat": legend,
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
            },
            "overrides": [],
        },
        "options": {
            "legend": {
                "displayMode": "list",
                "placement": "bottom",
            },
            "tooltip": {
                "mode": "single",
            },
        },
    }


panels = [
    stat_panel(
        1,
        "Request Latency",
        "com_project12_workloadmetrics_latencyms",
        0,
        0,
        "ms",
    ),
    stat_panel(
        2,
        "Error Rate",
        "com_project12_workloadmetrics_errorrate * 100",
        6,
        0,
        "percent",
    ),
    stat_panel(
        3,
        "Consumer Lag",
        "com_project12_workloadmetrics_consumerlag",
        12,
        0,
    ),
    stat_panel(
        4,
        "Queue Depth",
        "com_project12_workloadmetrics_queuedepth",
        18,
        0,
    ),
    stat_panel(
        5,
        "Database Latency",
        "com_project12_workloadmetrics_databaselatencyms",
        0,
        4,
        "ms",
    ),
    stat_panel(
        6,
        "JVM Heap Used",
        "java_lang_memory_heapmemoryusage_used",
        6,
        4,
        "bytes",
    ),
    stat_panel(
        7,
        "JVM Heap Utilization",
        (
            "100 * "
            "java_lang_memory_heapmemoryusage_used / "
            "java_lang_memory_heapmemoryusage_max"
        ),
        12,
        4,
        "percent",
    ),
    stat_panel(
        8,
        "Prometheus Target",
        'up{job="project12-java-workload"}',
        18,
        4,
    ),
    time_series_panel(
        9,
        "Application Latency",
        "com_project12_workloadmetrics_latencyms",
        "latency",
        0,
        8,
        "ms",
    ),
    time_series_panel(
        10,
        "Consumer Lag",
        "com_project12_workloadmetrics_consumerlag",
        "consumer lag",
        12,
        8,
    ),
    time_series_panel(
        11,
        "Error Rate",
        "com_project12_workloadmetrics_errorrate * 100",
        "error rate",
        0,
        16,
        "percent",
    ),
    time_series_panel(
        12,
        "Queue Depth",
        "com_project12_workloadmetrics_queuedepth",
        "queue depth",
        12,
        16,
    ),
    time_series_panel(
        13,
        "Retries / Minute",
        (
            "increase("
            "com_project12_workloadmetrics_retrycount[1m]"
            ")"
        ),
        "retries",
        0,
        24,
    ),
    time_series_panel(
        14,
        "TLS Failures / Minute",
        (
            "increase("
            "com_project12_workloadmetrics_tlsfailures[1m]"
            ")"
        ),
        "TLS failures",
        12,
        24,
    ),
    time_series_panel(
        15,
        "Authentication Failures / Minute",
        (
            "increase("
            "com_project12_workloadmetrics_"
            "authenticationfailures[1m]"
            ")"
        ),
        "authentication failures",
        0,
        32,
    ),
    time_series_panel(
        16,
        "Database Latency",
        "com_project12_workloadmetrics_databaselatencyms",
        "database latency",
        12,
        32,
        "ms",
    ),
    time_series_panel(
        17,
        "JVM Heap Used",
        "java_lang_memory_heapmemoryusage_used",
        "heap used",
        0,
        40,
        "bytes",
    ),
    time_series_panel(
        18,
        "Young GC Collections / Minute",
        (
            "increase("
            "java_lang_g1_young_generation_"
            "collectioncount[1m]"
            ")"
        ),
        "young GC",
        12,
        40,
    ),
]


dashboard = {
    "id": None,
    "uid": "project12-ops",
    "title": (
        "Project 12 - Autonomous Resilience Operations"
    ),
    "tags": [
        "project12",
        "sre",
        "prometheus",
        "jmx",
        "agentic-ai",
    ],
    "timezone": "browser",
    "schemaVersion": 41,
    "version": 1,
    "refresh": "5s",
    "time": {
        "from": "now-15m",
        "to": "now",
    },
    "panels": panels,
}


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    json.dumps(
        dashboard,
        indent=2,
    )
)

print(
    f"GRAFANA_DASHBOARD_CREATED={OUTPUT}"
)

print(
    f"PANEL_COUNT={len(panels)}"
)
