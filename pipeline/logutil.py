"""Run logging: every run writes a dated log file into data/runs/.
A failure must produce a stack trace in that log, not an improvisation."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from pipeline.config import DATA_DIR

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def new_run_logger(job: str) -> tuple[logging.Logger, Path]:
    runs = DATA_DIR / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = runs / f"{stamp}-{job}.log"

    logger = logging.getLogger(f"run.{job}.{stamp}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fh = logging.FileHandler(path)
    fh.setFormatter(logging.Formatter(FORMAT))
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger, path
