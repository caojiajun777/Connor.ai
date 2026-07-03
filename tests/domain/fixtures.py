"""Representative domain fixtures for Connor.ai Phase 1 tests."""

from datetime import date, datetime, timedelta, timezone

from app.domain import (
    AgentRole,
    ArchivedSignal,
    ArchiveReason,
    CandidateCategory,
    CandidateItem,
    ClusterTimelineEntry,
    ConfidenceLevel,
    DailyReport,
    EvaluationDecision,
    EvaluationResult,
    EvaluationType,
    EvidenceItem,
    EvidenceMapEntry,
    EvidenceStrength,
    EventCluster,
    IntelligenceThread,
    LaterOutcome,
    PriorityLevel,
    ReportItem,
    ReportSection,
    ReportStatus,
    RunPhase,
    RunState,
    RunStatus,
    SignalStatus,
    SourceAccessLevel,
    SourceType,
    ThreadStatus,
    ThreadTimelineEntry,
    ToolEnvelope,
    ToolEnvelopeItem,
    TraceEvent,
    TraceEventType,
    TraceStatus,
    WatchHistoryEntry,
    WatchlistItem,
    WatchlistUpdate,
    WatchStatus,
    WatchTier,
)

RUN_ID = "run_2026_07_03"
BASE_TIME = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)


def run_state_fixture() -> RunState:
    return RunState(
        id=RUN_ID,
        report_date=date(2026, 7, 3),
        objective="Generate the Connor.ai daily intelligence report for AI, semis, and tech finance.",
        phase=RunPhase.SCOUTING,
        status=RunStatus.RUNNING,
        enabled_sources=[
            SourceType.HACKER_NEWS,
            SourceType.GITHUB,
            SourceType.API_CHANGELOG,
            SourceType.INVESTOR_RELATIONS,
        ],
        created_at=BASE_TIME,
    )


def early_signal_bundle() -> dict[str, object]:
    evidence_1 = EvidenceItem(
        id="ev_openai_hn_reasoning",
        run_id=RUN_ID,
        source_type=SourceType.HACKER_NEWS,
        source_name="Hacker News",
        access_level=SourceAccessLevel.PUBLIC,
        strength=EvidenceStrength.WEAK,
        url="https://news.ycombinator.com/item?id=100001",
        title="Discussion about new OpenAI API behavior",
        author="hn_user_42",
        published_at=BASE_TIME - timedelta(hours=2),
        retrieved_at=BASE_TIME,
        snippet="A user claims seeing a new reasoning-control API option in an error response.",
        raw_hash="sha256:early-hn",
        created_at=BASE_TIME,
    )
    evidence_2 = EvidenceItem(
        id="ev_openai_wrapper_commit",
        run_id=RUN_ID,
        source_type=SourceType.GITHUB,
        source_name="GitHub",
        access_level=SourceAccessLevel.PUBLIC,
        strength=EvidenceStrength.MODERATE,
        url="https://github.com/example/openai-wrapper/commit/abc",
        title="Add mapping for reasoning-control option",
        author="wrapper_maintainer",
        published_at=BASE_TIME - timedelta(hours=1),
        retrieved_at=BASE_TIME,
        snippet="A third-party wrapper added a field resembling a reasoning effort option.",
        raw_hash="sha256:early-github",
        created_at=BASE_TIME,
    )
    candidate = CandidateItem(
        id="cand_openai_reasoning_api",
        run_id=RUN_ID,
        category=CandidateCategory.EARLY_SIGNAL,
        signal_status=SignalStatus.GRAY_ROLLOUT_FEEDBACK,
        claim_summary=(
            "Community and third-party code signals suggest OpenAI may be testing a "
            "new reasoning-control API option."
        ),
        entities=["OpenAI"],
        topics=["api", "reasoning", "developer_tools"],
        evidence_ids=[evidence_1.id, evidence_2.id],
        uncertainty=ConfidenceLevel.LOW,
        evidence_strength=EvidenceStrength.MODERATE,
        why_it_matters="It could give developers finer control over reasoning cost and latency.",
        potential_impact="Agent frameworks may expose more explicit reasoning-budget controls.",
        followup_questions=[
            "Does the option appear in official API docs?",
            "Does it appear in first-party SDK commits?",
        ],
        created_by_agent=AgentRole.SOCIAL_SCOUT,
        created_at=BASE_TIME,
    )
    cluster = EventCluster(
        id="cl_openai_reasoning_api",
        run_id=RUN_ID,
        category=CandidateCategory.EARLY_SIGNAL,
        title="Possible OpenAI reasoning-control API option",
        canonical_claim=(
            "Multiple non-official signals point to a possible OpenAI reasoning-control "
            "API option, but no official docs or SDK confirmation exists."
        ),
        candidate_ids=[candidate.id],
        evidence_ids=[evidence_1.id, evidence_2.id],
        entities=["OpenAI"],
        topics=["api", "reasoning", "developer_tools"],
        timeline=[
            ClusterTimelineEntry(
                observed_at=BASE_TIME,
                summary="Community discussion and third-party wrapper commit were linked.",
                evidence_ids=[evidence_1.id, evidence_2.id],
                candidate_ids=[candidate.id],
            )
        ],
        conflict_summary="Official docs and first-party SDK have not confirmed the option.",
        dedupe_key="openai:reasoning-control-api",
        created_at=BASE_TIME,
    )
    evaluation = EvaluationResult(
        id="eval_openai_reasoning_frontier",
        run_id=RUN_ID,
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.FRONTIER,
        created_by_agent=AgentRole.FRONTIER_EVALUATOR,
        dimension_scores={
            "novelty": 8,
            "specificity": 7,
            "source_proximity": 4,
            "impact": 8,
            "trackability": 9,
        },
        total_score=7.2,
        decision=EvaluationDecision.SELECT_EARLY_SIGNAL,
        reasoning_summary=(
            "The signal is specific and trackable but remains unconfirmed by official docs."
        ),
        required_followups=[
            "Monitor OpenAI API changelog.",
            "Monitor first-party SDK commits.",
        ],
        created_at=BASE_TIME,
    )
    watch = WatchlistItem(
        id="watch_openai_reasoning_api",
        run_id=RUN_ID,
        topic="OpenAI reasoning-control API changes",
        thesis="OpenAI may be exposing finer-grained developer controls for reasoning cost.",
        watch_tier=WatchTier.SHORT,
        status=WatchStatus.ACTIVE,
        priority=PriorityLevel.HIGH,
        ttl_days=7,
        watch_until=BASE_TIME + timedelta(days=7),
        revisit_cadence_days=1,
        last_signal_at=BASE_TIME,
        decay_score=0.1,
        reactivation_rules=[
            "Reactivate if official docs, SDK commits, or multiple independent users mention it."
        ],
        open_questions=["Is this an internal-only parameter or a public API change?"],
        entities=["OpenAI"],
        topics=["api", "reasoning"],
        evidence_ids=[evidence_1.id, evidence_2.id],
        cluster_ids=[cluster.id],
        history=[
            WatchHistoryEntry(
                at=BASE_TIME,
                summary="Short watch created from community and code signals.",
                evidence_ids=[evidence_1.id, evidence_2.id],
            )
        ],
        created_at=BASE_TIME,
    )
    archive = ArchivedSignal(
        id="arch_openai_reasoning_api",
        run_id=RUN_ID,
        original_cluster_id=cluster.id,
        original_watchlist_id=watch.id,
        archive_reason=ArchiveReason.TTL_EXPIRED,
        archived_at=BASE_TIME + timedelta(days=8),
        final_state="No official confirmation during short-watch window.",
        reactivation_hint="Reactivate if API changelog or SDK mentions reasoning-control fields.",
        evidence_ids=[evidence_1.id, evidence_2.id],
        created_at=BASE_TIME + timedelta(days=8),
    )
    thread = IntelligenceThread(
        id="thread_openai_reasoning_api",
        title="OpenAI reasoning-control API evolution",
        status=ThreadStatus.ACTIVE,
        importance=PriorityLevel.HIGH,
        entities=["OpenAI"],
        topics=["api", "reasoning", "developer_tools"],
        current_thesis="OpenAI may be moving toward more explicit reasoning budget controls.",
        timeline=[
            ThreadTimelineEntry(
                event_at=BASE_TIME,
                summary="Early community and code signals appeared.",
                confidence_at_time=ConfidenceLevel.LOW,
                later_outcome=LaterOutcome.PENDING,
                cluster_id=cluster.id,
                watchlist_id=watch.id,
                evidence_ids=[evidence_1.id, evidence_2.id],
            ),
            ThreadTimelineEntry(
                event_at=BASE_TIME + timedelta(days=8),
                summary="Short watch expired and was archived without confirmation.",
                confidence_at_time=ConfidenceLevel.LOW,
                later_outcome=LaterOutcome.UNRESOLVED,
                archive_id=archive.id,
                evidence_ids=[evidence_1.id, evidence_2.id],
            ),
        ],
        open_questions=["Will later official API docs confirm this signal?"],
        linked_cluster_ids=[cluster.id],
        linked_watchlist_ids=[watch.id],
        linked_archive_ids=[archive.id],
        created_at=BASE_TIME,
    )
    trace = TraceEvent(
        id="trace_eval_openai_reasoning",
        run_id=RUN_ID,
        seq=1,
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        event_type=TraceEventType.EVALUATION_CREATED,
        status=TraceStatus.SUCCEEDED,
        summary="Frontier evaluator selected the OpenAI API signal as an early signal.",
        reasoning_summary="Specific and trackable signal, but no official confirmation.",
        created_at=BASE_TIME,
    )
    return {
        "evidence": [evidence_1, evidence_2],
        "candidate": candidate,
        "cluster": cluster,
        "evaluation": evaluation,
        "watch": watch,
        "archive": archive,
        "thread": thread,
        "trace": trace,
    }


def confirmed_event_bundle() -> dict[str, object]:
    evidence = EvidenceItem(
        id="ev_anthropic_api_update",
        run_id=RUN_ID,
        source_type=SourceType.API_CHANGELOG,
        source_name="Anthropic API changelog",
        access_level=SourceAccessLevel.PUBLIC,
        strength=EvidenceStrength.OFFICIAL,
        url="https://docs.anthropic.com/en/release-notes/api",
        title="Anthropic API release notes",
        published_at=BASE_TIME,
        retrieved_at=BASE_TIME,
        snippet="Official changelog announces a new model capability and API update.",
        raw_hash="sha256:anthropic-official",
        created_at=BASE_TIME,
    )
    candidate = CandidateItem(
        id="cand_anthropic_api_update",
        run_id=RUN_ID,
        category=CandidateCategory.CONFIRMED_EVENT,
        signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
        claim_summary="Anthropic officially announced a model/API capability update.",
        entities=["Anthropic"],
        topics=["api", "model_release"],
        evidence_ids=[evidence.id],
        uncertainty=ConfidenceLevel.HIGH,
        evidence_strength=EvidenceStrength.OFFICIAL,
        why_it_matters="Official API changes affect production integrations and agent tooling.",
        potential_impact="Developers may need to update routing, evals, and cost controls.",
        created_by_agent=AgentRole.OFFICIAL_SCOUT,
        created_at=BASE_TIME,
    )
    cluster = EventCluster(
        id="cl_anthropic_api_update",
        run_id=RUN_ID,
        category=CandidateCategory.CONFIRMED_EVENT,
        title="Anthropic official API update",
        canonical_claim="Anthropic officially announced a model/API capability update.",
        candidate_ids=[candidate.id],
        evidence_ids=[evidence.id],
        entities=["Anthropic"],
        topics=["api", "model_release"],
        timeline=[
            ClusterTimelineEntry(
                observed_at=BASE_TIME,
                summary="Official changelog entry captured.",
                evidence_ids=[evidence.id],
                candidate_ids=[candidate.id],
            )
        ],
        dedupe_key="anthropic:official-api-update",
        selected=True,
        created_at=BASE_TIME,
    )
    evaluation = EvaluationResult(
        id="eval_anthropic_event",
        run_id=RUN_ID,
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.EVENT,
        created_by_agent=AgentRole.EVENT_EVALUATOR,
        dimension_scores={
            "confirmation": 10,
            "impact_scale": 7,
            "expectation_change": 6,
            "product_impact": 7,
        },
        total_score=7.5,
        decision=EvaluationDecision.SELECT_CONFIRMED,
        reasoning_summary="Official changelog confirms the update and product impact is material.",
        created_at=BASE_TIME,
    )
    return {
        "evidence": [evidence],
        "candidate": candidate,
        "cluster": cluster,
        "evaluation": evaluation,
    }


def tech_finance_bundle() -> dict[str, object]:
    evidence = EvidenceItem(
        id="ev_nvda_blackwell_hbm",
        run_id=RUN_ID,
        source_type=SourceType.INVESTOR_RELATIONS,
        source_name="NVIDIA Investor Relations",
        access_level=SourceAccessLevel.PUBLIC,
        strength=EvidenceStrength.STRONG,
        url="https://investor.nvidia.com/",
        title="NVIDIA investor update on data center demand",
        published_at=BASE_TIME,
        retrieved_at=BASE_TIME,
        snippet="Management commentary references data-center demand and supply constraints.",
        raw_hash="sha256:nvda-ir",
        created_at=BASE_TIME,
    )
    candidate = CandidateItem(
        id="cand_nvda_blackwell_hbm",
        run_id=RUN_ID,
        category=CandidateCategory.TECH_FINANCE,
        signal_status=SignalStatus.NOT_APPLICABLE,
        claim_summary="NVIDIA data-center demand commentary points to continued HBM and server supply-chain pressure.",
        entities=["NVIDIA", "TSMC", "SK hynix"],
        tickers=["NVDA", "TSM"],
        topics=["blackwell", "hbm", "ai_capex", "data_center"],
        evidence_ids=[evidence.id],
        uncertainty=ConfidenceLevel.MEDIUM,
        evidence_strength=EvidenceStrength.STRONG,
        why_it_matters="Supply-chain constraints can shape AI server revenue timing and margins.",
        potential_impact="Positive for HBM suppliers and advanced packaging capacity; timing risk for AI server ramps.",
        created_by_agent=AgentRole.FINANCE_SCOUT,
        created_at=BASE_TIME,
    )
    cluster = EventCluster(
        id="cl_nvda_blackwell_hbm",
        run_id=RUN_ID,
        category=CandidateCategory.TECH_FINANCE,
        title="NVIDIA AI server demand and HBM supply chain",
        canonical_claim=(
            "NVIDIA investor commentary suggests AI data-center demand remains strong, "
            "with implications for HBM, CoWoS, and AI server supply chains."
        ),
        candidate_ids=[candidate.id],
        evidence_ids=[evidence.id],
        entities=["NVIDIA", "TSMC", "SK hynix"],
        tickers=["NVDA", "TSM"],
        topics=["blackwell", "hbm", "ai_capex", "data_center"],
        timeline=[
            ClusterTimelineEntry(
                observed_at=BASE_TIME,
                summary="Investor commentary captured and linked to supply-chain impact.",
                evidence_ids=[evidence.id],
                candidate_ids=[candidate.id],
            )
        ],
        dedupe_key="nvda:blackwell-hbm-demand",
        selected=True,
        created_at=BASE_TIME,
    )
    evaluation = EvaluationResult(
        id="eval_nvda_market",
        run_id=RUN_ID,
        cluster_id=cluster.id,
        evaluator_type=EvaluationType.MARKET,
        created_by_agent=AgentRole.MARKET_EVALUATOR,
        dimension_scores={
            "ai_relevance": 9,
            "market_impact": 8,
            "supply_chain_impact": 8,
            "ticker_relevance": 9,
        },
        total_score=8.5,
        decision=EvaluationDecision.SELECT_CONFIRMED,
        reasoning_summary="High AI relevance with clear ticker and supply-chain implications.",
        created_at=BASE_TIME,
    )
    return {
        "evidence": [evidence],
        "candidate": candidate,
        "cluster": cluster,
        "evaluation": evaluation,
    }


def daily_report_fixture() -> DailyReport:
    early = early_signal_bundle()
    finance = tech_finance_bundle()
    early_evidence = early["evidence"]
    early_cluster = early["cluster"]
    finance_evidence = finance["evidence"]
    finance_cluster = finance["cluster"]

    early_item = ReportItem(
        item_id="item_openai_reasoning_api",
        title="OpenAI suspected reasoning-control API test",
        category=CandidateCategory.EARLY_SIGNAL,
        status_label="Unconfirmed gray rollout feedback",
        core_information=(
            "Community discussion and third-party code suggest a possible new reasoning-control option."
        ),
        why_it_matters="It may affect how developers tune cost, latency, and reasoning depth.",
        potential_impact="If confirmed, agent frameworks may expose finer reasoning controls.",
        evidence_ids=[item.id for item in early_evidence],
        cluster_ids=[early_cluster.id],
        followup_points=["Check official docs and first-party SDK commits."],
        uncertainty_label="low confidence, high trackability",
    )
    finance_item = ReportItem(
        item_id="item_nvda_hbm",
        title="NVIDIA AI demand keeps HBM and packaging in focus",
        category=CandidateCategory.TECH_FINANCE,
        status_label="Investor-relations sourced signal",
        core_information="NVIDIA data-center commentary points to ongoing supply-chain pressure.",
        why_it_matters="AI server revenue timing depends on HBM and advanced packaging capacity.",
        potential_impact="Relevant for NVDA, TSM, HBM suppliers, and AI server vendors.",
        key_data=["Data-center demand commentary", "HBM and advanced packaging constraints"],
        tickers=["NVDA", "TSM"],
        evidence_ids=[item.id for item in finance_evidence],
        cluster_ids=[finance_cluster.id],
        followup_points=["Watch capex guidance and supplier commentary."],
    )
    sections = [
        ReportSection(
            section_id="early_signals",
            title="Early Signals",
            items=[early_item],
        ),
        ReportSection(
            section_id="tech_finance",
            title="Tech-Finance",
            items=[finance_item],
        ),
    ]
    return DailyReport(
        id="report_2026_07_03",
        run_id=RUN_ID,
        report_date=date(2026, 7, 3),
        status=ReportStatus.FINAL,
        full_markdown="# Connor.ai Daily Intelligence\n\n## Early Signals\n...",
        full_json={
            "report_date": "2026-07-03",
            "sections": [
                {"section_id": "early_signals", "items": [early_item.model_dump(mode="json")]},
                {"section_id": "tech_finance", "items": [finance_item.model_dump(mode="json")]},
            ],
        },
        sections=sections,
        evidence_map=[
            EvidenceMapEntry(
                report_item_id=early_item.item_id,
                evidence_ids=early_item.evidence_ids,
                cluster_ids=early_item.cluster_ids,
                trace_event_ids=["trace_eval_openai_reasoning"],
            ),
            EvidenceMapEntry(
                report_item_id=finance_item.item_id,
                evidence_ids=finance_item.evidence_ids,
                cluster_ids=finance_item.cluster_ids,
                trace_event_ids=["trace_eval_nvda_market"],
            ),
        ],
        watchlist_updates=[
            WatchlistUpdate(
                watchlist_id="watch_openai_reasoning_api",
                topic="OpenAI reasoning-control API changes",
                current_status="active short watch",
                new_developments=["Community and code signals appeared."],
                next_watch=["OpenAI API changelog", "OpenAI SDK commits"],
                evidence_ids=early_item.evidence_ids,
            )
        ],
        trace_timeline_ids=["trace_eval_openai_reasoning", "trace_eval_nvda_market"],
        review_result_ids=["review_final_2026_07_03"],
        quality_score=8.7,
        created_at=BASE_TIME,
    )


def tool_envelope_fixture() -> ToolEnvelope:
    return ToolEnvelope(
        tool_name="github_search",
        source_type=SourceType.GITHUB,
        query="reasoning control OpenAI API",
        retrieved_at=BASE_TIME,
        items=[
            ToolEnvelopeItem(
                title="OpenAI wrapper commit",
                url="https://github.com/example/openai-wrapper/commit/abc",
                author="wrapper_maintainer",
                published_at=BASE_TIME - timedelta(hours=1),
                snippet="Adds mapping for a reasoning-control option.",
                raw_hash="sha256:tool-item",
            )
        ],
    )

