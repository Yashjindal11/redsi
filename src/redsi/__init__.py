"""RedSI: systematically discover, reproduce, measure, and prevent failures in AI systems."""

from redsi._version import __version__
from redsi.campaign import CampaignConfig, RunArtifact
from redsi.core import (
    Document,
    Finding,
    FindingStatus,
    Message,
    Severity,
    SeverityPolicy,
    SeverityRule,
    TargetInput,
    TargetOutput,
    TestCase,
    ToolCall,
    ToolSpec,
    Verdict,
)
from redsi.sdk import RedSI
from redsi.store import RunStore
from redsi.targets import Target, TargetAdapter

__all__ = [
    "CampaignConfig",
    "Document",
    "Finding",
    "FindingStatus",
    "Message",
    "RedSI",
    "RunArtifact",
    "RunStore",
    "Severity",
    "SeverityPolicy",
    "SeverityRule",
    "Target",
    "TargetAdapter",
    "TargetInput",
    "TargetOutput",
    "TestCase",
    "ToolCall",
    "ToolSpec",
    "Verdict",
    "__version__",
]
