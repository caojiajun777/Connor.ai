"""Built-in deterministic tools for early development and tests."""

from app.domain import (
    AgentRole,
    EvidenceStrength,
    SourceAccessLevel,
    SourceType,
    ToolEnvelope,
    ToolEnvelopeItem,
)
from app.domain.base import utc_now
from app.tools.base import ToolExecutionContext, ToolSpec
from app.tools.registry import ToolRegistry


def manual_seed_tool(context: ToolExecutionContext) -> ToolEnvelope:
    """Turn user/test-provided items into a manual-source ToolEnvelope."""

    items = [
        ToolEnvelopeItem.model_validate(item)
        for item in context.params.get("items", [])
    ]
    return ToolEnvelope(
        tool_name="manual_seed",
        source_type=SourceType.MANUAL,
        query=context.query,
        retrieved_at=context.params.get("retrieved_at", utc_now()),
        items=items,
        metadata={"seed_reason": context.params.get("seed_reason", "manual input")},
    )


def mock_search_tool(context: ToolExecutionContext) -> ToolEnvelope:
    """Return deterministic mock search results for tool/harness development."""

    items_payload = context.params.get("items")
    if items_payload is None:
        items_payload = [
            {
                "title": f"Mock result for {context.query}",
                "url": "https://example.com/mock-result",
                "snippet": f"Deterministic mock result generated for query: {context.query}",
                "raw_ref": f"mock:{context.query}",
            }
        ]

    items = [ToolEnvelopeItem.model_validate(item) for item in items_payload]
    return ToolEnvelope(
        tool_name="mock_search",
        source_type=SourceType.OTHER,
        query=context.query,
        retrieved_at=context.params.get("retrieved_at", utc_now()),
        items=items,
        metadata={"mock": True},
    )


def create_default_tool_registry() -> ToolRegistry:
    """Create the Phase 4 default registry with deterministic built-in tools."""

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="manual_seed",
            description="Inject manually curated source items into a run.",
            source_type=SourceType.MANUAL,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.SOCIAL_SCOUT,
                    AgentRole.CODE_MODEL_SCOUT,
                    AgentRole.RESEARCH_SCOUT,
                    AgentRole.OFFICIAL_SCOUT,
                    AgentRole.FINANCE_SCOUT,
                }
            ),
            default_source_name="manual_seed",
            default_access_level=SourceAccessLevel.INTERNAL,
            default_evidence_strength=EvidenceStrength.MODERATE,
        ),
        manual_seed_tool,
    )
    registry.register(
        ToolSpec(
            name="mock_search",
            description="Deterministic mock search tool for tests and harness development.",
            source_type=SourceType.OTHER,
            allowed_agent_roles=frozenset(set(AgentRole) - {AgentRole.SYSTEM}),
            default_source_name="mock_search",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.WEAK,
        ),
        mock_search_tool,
    )
    return registry

