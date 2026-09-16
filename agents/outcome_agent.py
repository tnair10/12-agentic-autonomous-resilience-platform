#!/usr/bin/env python3

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data" / "incidents" / "incident_memory.db"


def load_json(path):
    return json.loads(
        Path(path).read_text()
    )


def connect():
    connection = sqlite3.connect(
        DB_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


def initialize(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS remediation_stats (
            root_cause TEXT NOT NULL,
            remediation TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY (
                root_cause,
                remediation
            )
        )
        """
    )

    connection.commit()


def record_outcome(
    connection,
    root_cause,
    remediation,
    success,
):
    existing = connection.execute(
        """
        SELECT
            attempts,
            successes,
            failures
        FROM remediation_stats
        WHERE
            root_cause = ?
            AND remediation = ?
        """,
        (
            root_cause,
            remediation,
        ),
    ).fetchone()

    if existing:
        attempts = (
            existing["attempts"]
            + 1
        )

        successes = (
            existing["successes"]
            + (
                1
                if success
                else 0
            )
        )

        failures = (
            existing["failures"]
            + (
                0
                if success
                else 1
            )
        )

        connection.execute(
            """
            UPDATE remediation_stats
            SET
                attempts = ?,
                successes = ?,
                failures = ?
            WHERE
                root_cause = ?
                AND remediation = ?
            """,
            (
                attempts,
                successes,
                failures,
                root_cause,
                remediation,
            ),
        )

    else:
        attempts = 1

        successes = (
            1
            if success
            else 0
        )

        failures = (
            0
            if success
            else 1
        )

        connection.execute(
            """
            INSERT INTO remediation_stats (
                root_cause,
                remediation,
                attempts,
                successes,
                failures
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                root_cause,
                remediation,
                attempts,
                successes,
                failures,
            ),
        )

    connection.commit()

    return {
        "root_cause":
            root_cause,

        "remediation":
            remediation,

        "attempts":
            attempts,

        "successes":
            successes,

        "failures":
            failures,

        "success_rate":
            round(
                successes / attempts,
                4,
            ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Project 12 remediation "
            "outcome learning agent"
        )
    )

    parser.add_argument(
        "--remediation",
        default=(
            "results/incidents/"
            "latest-remediation.json"
        ),
    )

    args = parser.parse_args()

    remediation = load_json(
        args.remediation
    )

    root_cause = remediation.get(
        "root_cause"
    )

    action = remediation.get(
        "action"
    )

    success = (
        remediation.get(
            "status"
        )
        == "RECOVERED"
        and remediation.get(
            "verification",
            {},
        ).get(
            "recovered"
        )
        is True
    )

    if not root_cause:
        raise RuntimeError(
            "Remediation record has no root cause"
        )

    if not action:
        raise RuntimeError(
            "Remediation record has no action"
        )

    connection = connect()

    initialize(
        connection
    )

    result = record_outcome(
        connection,
        root_cause,
        action,
        success,
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print(
        "REMEDIATION_LEARNING=PASS"
    )


if __name__ == "__main__":
    main()
