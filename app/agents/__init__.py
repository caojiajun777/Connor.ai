"""AgentScope integration layer."""

from app.agents.agentscope_tools import AgentScopeToolBridge, ConnorFunctionTool
from app.agents.config import AgentExecutionConfig, AgentRoleConfig
from app.agents.outputs import (
    AgentStructuredOutput,
    ArchiveDraft,
    CandidateDraft,
    ClusterDraft,
    ClusterTimelineDraft,
    ClustererOutput,
    EditorOutput,
    EvaluationDraft,
    EvaluatorOutput,
    ReportDraft,
    ReportItemDraft,
    ReportSectionDraft,
    ReviewDraft,
    ReviewIssueDraft,
    ReviewerOutput,
    ScoutOutput,
    ThreadDraft,
    ThreadTimelineDraft,
    WatchlistAgentOutput,
    WatchlistDraft,
    WriterOutput,
)
from app.agents.model_factory import create_deepseek_model_factory
from app.agents.registry import AgentRoleRegistry, create_default_agent_role_registry
from app.agents.runner import AgentRunner, AgentScopeModelFactory
from app.agents.schemas import (
    AgentRunRequest,
    AgentRunResult,
    AgentScopeExecutionError,
)

__all__ = [
    "AgentExecutionConfig",
    "AgentRoleConfig",
    "AgentRoleRegistry",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRunner",
    "AgentScopeExecutionError",
    "AgentScopeModelFactory",
    "AgentScopeToolBridge",
    "AgentStructuredOutput",
    "ArchiveDraft",
    "CandidateDraft",
    "ClusterDraft",
    "ClusterTimelineDraft",
    "ClustererOutput",
    "ConnorFunctionTool",
    "EditorOutput",
    "EvaluationDraft",
    "EvaluatorOutput",
    "ReportDraft",
    "ReportItemDraft",
    "ReportSectionDraft",
    "ReviewDraft",
    "ReviewIssueDraft",
    "ReviewerOutput",
    "ScoutOutput",
    "ThreadDraft",
    "ThreadTimelineDraft",
    "WatchlistAgentOutput",
    "WatchlistDraft",
    "WriterOutput",
    "create_deepseek_model_factory",
    "create_default_agent_role_registry",
]
