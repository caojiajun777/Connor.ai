"""String enums used across Connor.ai domain contracts."""

from enum import Enum


class StrEnum(str, Enum):
    """JSON-friendly string enum."""

    def __str__(self) -> str:
        return self.value


class RunPhase(StrEnum):
    INITIALIZE = "initialize"
    COLLECT_PLANNING = "collect_planning"
    SCOUTING = "scouting"
    CLUSTERING = "clustering"
    EVALUATING = "evaluating"
    EVALUATION_GATE = "evaluation_gate"
    FOLLOWUP = "followup"
    WATCHLIST_UPDATE = "watchlist_update"
    WRITING = "writing"
    REVIEWING = "reviewing"
    EDITING = "editing"
    FINAL_REVIEW = "final_review"
    FINALIZED = "finalized"
    ARCHIVED = "archived"
    FAILED = "failed"


class RunStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SOCIAL_SCOUT = "social_scout"
    CODE_MODEL_SCOUT = "code_model_scout"
    RESEARCH_SCOUT = "research_scout"
    OFFICIAL_SCOUT = "official_scout"
    FINANCE_SCOUT = "finance_scout"
    CLUSTERER = "clusterer"
    FRONTIER_EVALUATOR = "frontier_evaluator"
    EVENT_EVALUATOR = "event_evaluator"
    MARKET_EVALUATOR = "market_evaluator"
    WATCHLIST_AGENT = "watchlist_agent"
    WRITER = "writer"
    REVIEWER = "reviewer"
    EDITOR = "editor"
    SYSTEM = "system"


class SourceType(StrEnum):
    X = "x"
    REDDIT = "reddit"
    HACKER_NEWS = "hacker_news"
    BLUESKY = "bluesky"
    PRODUCT_HUNT = "product_hunt"
    GITHUB = "github"
    HUGGING_FACE = "hugging_face"
    NPM = "npm"
    PYPI = "pypi"
    DOCKER_HUB = "docker_hub"
    ARXIV = "arxiv"
    OPENREVIEW = "openreview"
    PAPERS_WITH_CODE = "papers_with_code"
    OFFICIAL_BLOG = "official_blog"
    API_CHANGELOG = "api_changelog"
    DOCS = "docs"
    INVESTOR_RELATIONS = "investor_relations"
    SEC_FILING = "sec_filing"
    EARNINGS_CALL = "earnings_call"
    SEMIANALYSIS = "semianalysis"
    THE_INFORMATION = "the_information"
    REUTERS = "reuters"
    BLOOMBERG = "bloomberg"
    WSJ = "wsj"
    CNBC = "cnbc"
    MANUAL = "manual"
    OTHER = "other"


class SourceAccessLevel(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    PAID = "paid"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class CandidateCategory(StrEnum):
    EARLY_SIGNAL = "early_signal"
    CONFIRMED_EVENT = "confirmed_event"
    TECH_FINANCE = "tech_finance"
    RESEARCH = "research"
    CODE_MODEL = "code_model"
    OFFICIAL_UPDATE = "official_update"
    WATCHLIST_UPDATE = "watchlist_update"
    OTHER = "other"


class SignalStatus(StrEnum):
    UNCONFIRMED_LEAK = "unconfirmed_leak"
    GRAY_ROLLOUT_FEEDBACK = "gray_rollout_feedback"
    CODE_ANOMALY = "code_anomaly"
    RESEARCHER_HINT = "researcher_hint"
    COMMUNITY_RUMOR = "community_rumor"
    SINGLE_SOURCE_SIGNAL = "single_source_signal"
    MANUAL_HYPOTHESIS = "manual_hypothesis"
    OFFICIAL_CONFIRMATION = "official_confirmation"
    CONFIRMED_FACT = "confirmed_fact"
    NOT_APPLICABLE = "not_applicable"


class EvidenceStrength(StrEnum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    OFFICIAL = "official"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class EvaluationType(StrEnum):
    FRONTIER = "frontier"
    EVENT = "event"
    MARKET = "market"


class EvaluationDecision(StrEnum):
    SELECT_CONFIRMED = "select_confirmed"
    SELECT_EARLY_SIGNAL = "select_early_signal"
    SHORT_WATCH = "short_watch"
    FOLLOWUP_NOW = "followup_now"
    FOLLOWUP_LATER = "followup_later"
    RECLUSTER = "recluster"
    ARCHIVE = "archive"
    REJECT = "reject"


class WatchTier(StrEnum):
    SHORT = "short"
    EVENT = "event"
    STRATEGIC = "strategic"


class WatchStatus(StrEnum):
    ACTIVE = "active"
    COOLING = "cooling"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    REACTIVATED = "reactivated"


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"
    RESOLVED = "resolved"


class LaterOutcome(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISPROVEN = "disproven"
    SUPERSEDED = "superseded"
    STALE = "stale"
    UNRESOLVED = "unresolved"


class ArchiveReason(StrEnum):
    TTL_EXPIRED = "ttl_expired"
    SUPERSEDED = "superseded"
    DISPROVEN = "disproven"
    LOW_VALUE = "low_value"
    MERGED = "merged"
    NO_NEW_SIGNAL = "no_new_signal"
    MANUAL = "manual"


class PriorityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ArtifactKind(StrEnum):
    RAW_TOOL_RESPONSE = "raw_tool_response"
    RAW_PAGE_SNAPSHOT = "raw_page_snapshot"
    NORMALIZED_PAYLOAD = "normalized_payload"
    MODEL_PROMPT = "model_prompt"
    MODEL_OUTPUT = "model_output"
    REPORT_SNAPSHOT = "report_snapshot"
    TRACE_PAYLOAD = "trace_payload"
    FIXTURE = "fixture"


class ArtifactStorage(StrEnum):
    INLINE = "inline"
    FILE = "file"
    OBJECT_STORE = "object_store"
    DATABASE = "database"


class TraceEventType(StrEnum):
    RUN_STARTED = "run_started"
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    AGENT_DECISION = "agent_decision"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    EVIDENCE_CREATED = "evidence_created"
    CANDIDATE_CREATED = "candidate_created"
    CLUSTER_CREATED = "cluster_created"
    EVALUATION_CREATED = "evaluation_created"
    GATE_DECISION = "gate_decision"
    WATCHLIST_UPDATED = "watchlist_updated"
    ARCHIVE_CREATED = "archive_created"
    THREAD_UPDATED = "thread_updated"
    REPORT_DRAFTED = "report_drafted"
    REVIEW_COMPLETED = "review_completed"
    REPORT_EDITED = "report_edited"
    REPORT_FINALIZED = "report_finalized"
    ERROR = "error"


class TraceStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolCallStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SKIPPED = "skipped"


class ModelCallStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    NEEDS_REVISION = "needs_revision"
    FINAL = "final"
    FAILED = "failed"
    ARCHIVED = "archived"


class ReviewDecision(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    REJECT = "reject"
    REOPEN_COLLECT = "reopen_collect"


class ObjectType(StrEnum):
    RUN = "run"
    EVIDENCE = "evidence"
    CANDIDATE = "candidate"
    CLUSTER = "cluster"
    EVALUATION = "evaluation"
    WATCHLIST = "watchlist"
    ARCHIVE = "archive"
    THREAD = "thread"
    REPORT = "report"
    TRACE_EVENT = "trace_event"
    TOOL_CALL = "tool_call"
    MODEL_CALL = "model_call"
    ARTIFACT = "artifact"
    REVIEW = "review"

