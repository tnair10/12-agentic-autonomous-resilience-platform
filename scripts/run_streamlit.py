#!/usr/bin/env python3

import logging
import logging.handlers
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LOG_DIR = ROOT / "data" / "logs"

LOG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

LOG_FILE = (
    LOG_DIR
    / "streamlit.log"
)


handler = (
    logging.handlers
    .RotatingFileHandler(
        LOG_FILE,
        maxBytes=25 * 1024 * 1024,
        backupCount=5,
    )
)

handler.setFormatter(
    logging.Formatter(
        "%(asctime)s %(message)s"
    )
)

logger = logging.getLogger(
    "project12-streamlit"
)

logger.setLevel(
    logging.INFO
)

logger.addHandler(
    handler
)


command = [
    str(
        ROOT
        / ".venv"
        / "bin"
        / "streamlit"
    ),
    "run",
    str(
        ROOT
        / "app"
        / "streamlit_app.py"
    ),
    "--server.address",
    "127.0.0.1",
    "--server.port",
    "8501",
]


process = subprocess.Popen(
    command,
    cwd=ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)


def shutdown(
    signum,
    frame,
):
    logger.info(
        "Stopping Streamlit"
    )

    process.terminate()

    try:
        process.wait(
            timeout=10
        )

    except subprocess.TimeoutExpired:
        process.kill()

    sys.exit(0)


signal.signal(
    signal.SIGTERM,
    shutdown,
)

signal.signal(
    signal.SIGINT,
    shutdown,
)


logger.info(
    "Starting Project 12 Streamlit"
)

logger.info(
    "PID=%s",
    process.pid,
)


for line in process.stdout:
    logger.info(
        line.rstrip()
    )


returncode = process.wait()

logger.info(
    "Streamlit exited with code %s",
    returncode,
)

sys.exit(
    returncode
)
