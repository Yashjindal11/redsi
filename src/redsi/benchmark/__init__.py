"""Reproducible experiments on synthetic targets with planted faults."""

from redsi.benchmark.runner import MethodScore, render_markdown, run_benchmark, score, summarise
from redsi.benchmark.target import (
    FAULTS,
    PlantedFaultTarget,
    faults_fired,
    seed_tests,
    specification,
)

__all__ = [
    "FAULTS",
    "MethodScore",
    "PlantedFaultTarget",
    "faults_fired",
    "render_markdown",
    "run_benchmark",
    "score",
    "seed_tests",
    "specification",
    "summarise",
]
