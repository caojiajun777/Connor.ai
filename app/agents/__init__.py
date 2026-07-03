"""AgentScope integration layer."""

from app.agents.agentscope_tools import AgentScopeToolBridge, ConnorFunctionTool
from app.agents.config import AgentExecutionConfig, AgentRoleConfig
from app.agents.outputs import (
    AgentStructuredOutput,
    CandidateDraft,
    ClusterDraft,
    ClusterTimelineDraft,
    ClustererOutput,
    EditorOutput,
    EvaluatorOutput,
    ReviewerOutput,
    ScoutOutput,
    WriterOutput,
)
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
    "CandidateDraft",
    "ClusterDraft",
    "ClusterTimelineDraft",
    "ClustererOutput",
    "ConnorFunctionTool",
    "EditorOutput",
    "EvaluatorOutput",
    "ReviewerOutput",
    "ScoutOutput",
    "WriterOutput",
    "create_default_agent_role_registry",
]
