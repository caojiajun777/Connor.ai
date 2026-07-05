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
from app.tools.source_tools import (
    api_changelog_search_tool,
    arxiv_search_tool,
    github_code_search_tool,
    github_repository_search_tool,
    huggingface_dataset_search_tool,
    huggingface_model_search_tool,
    hacker_news_feed_search_tool,
    investor_relations_search_tool,
    official_feed_search_tool,
    openreview_note_search_tool,
    sec_company_facts_tool,
    sec_company_filings_tool,
)


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
    registry.register(
        ToolSpec(
            name="github_repository_search",
            description="Search public GitHub repositories for code/model/tooling signals.",
            source_type=SourceType.GITHUB,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.CODE_MODEL_SCOUT,
                }
            ),
            default_source_name="GitHub Search API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        github_repository_search_tool,
    )
    registry.register(
        ToolSpec(
            name="github_code_search",
            description="Search public GitHub code for SDK, API, model, and package signals.",
            source_type=SourceType.GITHUB,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.CODE_MODEL_SCOUT,
                }
            ),
            default_source_name="GitHub Code Search API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        github_code_search_tool,
    )
    registry.register(
        ToolSpec(
            name="huggingface_model_search",
            description="Search public Hugging Face model repositories for model-release signals.",
            source_type=SourceType.HUGGING_FACE,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.CODE_MODEL_SCOUT,
                    AgentRole.RESEARCH_SCOUT,
                }
            ),
            default_source_name="Hugging Face Hub API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        huggingface_model_search_tool,
    )
    registry.register(
        ToolSpec(
            name="huggingface_dataset_search",
            description="Search public Hugging Face datasets for benchmark and data-release signals.",
            source_type=SourceType.HUGGING_FACE,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.CODE_MODEL_SCOUT,
                    AgentRole.RESEARCH_SCOUT,
                }
            ),
            default_source_name="Hugging Face Hub API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        huggingface_dataset_search_tool,
    )
    registry.register(
        ToolSpec(
            name="arxiv_search",
            description="Search arXiv papers for research, benchmark, and model-method signals.",
            source_type=SourceType.ARXIV,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.RESEARCH_SCOUT,
                }
            ),
            default_source_name="arXiv API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        arxiv_search_tool,
    )
    registry.register(
        ToolSpec(
            name="openreview_note_search",
            description="Search OpenReview API 2 notes for papers, reviews, and venue signals.",
            source_type=SourceType.OPENREVIEW,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.RESEARCH_SCOUT,
                }
            ),
            default_source_name="OpenReview API 2",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.MODERATE,
            timeout_seconds=20,
        ),
        openreview_note_search_tool,
    )
    registry.register(
        ToolSpec(
            name="official_feed_search",
            description="Search curated official RSS/Atom blog feeds for confirmed product, model, and research updates.",
            source_type=SourceType.OFFICIAL_BLOG,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.OFFICIAL_SCOUT,
                }
            ),
            default_source_name="Official Feed Catalog",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.OFFICIAL,
            timeout_seconds=20,
        ),
        official_feed_search_tool,
    )
    registry.register(
        ToolSpec(
            name="api_changelog_search",
            description="Search curated official API changelog feeds/pages for confirmed API updates.",
            source_type=SourceType.API_CHANGELOG,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.OFFICIAL_SCOUT,
                }
            ),
            default_source_name="API Changelog Catalog",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.OFFICIAL,
            timeout_seconds=20,
        ),
        api_changelog_search_tool,
    )
    registry.register(
        ToolSpec(
            name="sec_company_filings",
            description="Fetch recent SEC EDGAR filings for a company by ticker or CIK.",
            source_type=SourceType.SEC_FILING,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.FINANCE_SCOUT,
                }
            ),
            default_source_name="SEC EDGAR Submissions API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.OFFICIAL,
            timeout_seconds=20,
        ),
        sec_company_filings_tool,
    )
    registry.register(
        ToolSpec(
            name="sec_company_facts",
            description="Fetch selected SEC XBRL company facts for a company by ticker or CIK.",
            source_type=SourceType.SEC_FILING,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.FINANCE_SCOUT,
                }
            ),
            default_source_name="SEC EDGAR Company Facts API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.OFFICIAL,
            timeout_seconds=20,
        ),
        sec_company_facts_tool,
    )
    registry.register(
        ToolSpec(
            name="investor_relations_search",
            description="Search curated company investor-relations pages for earnings, guidance, and AI infrastructure signals.",
            source_type=SourceType.INVESTOR_RELATIONS,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.FINANCE_SCOUT,
                }
            ),
            default_source_name="Investor Relations Catalog",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.STRONG,
            timeout_seconds=20,
        ),
        investor_relations_search_tool,
    )
    registry.register(
        ToolSpec(
            name="hacker_news_feed_search",
            description="Search bounded Hacker News official API feeds for community discussion signals.",
            source_type=SourceType.HACKER_NEWS,
            allowed_agent_roles=frozenset(
                {
                    AgentRole.ORCHESTRATOR,
                    AgentRole.SOCIAL_SCOUT,
                }
            ),
            default_source_name="Hacker News Firebase API",
            default_access_level=SourceAccessLevel.PUBLIC,
            default_evidence_strength=EvidenceStrength.WEAK,
            timeout_seconds=20,
        ),
        hacker_news_feed_search_tool,
    )
    return registry
