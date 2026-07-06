"""Clusterer output materialization tests."""

from __future__ import annotations

from app.agents.outputs import ClusterDraft, ClusterTimelineDraft, ClustererOutput
from app.agents.schemas import AgentRunResult
from app.clusterer.materialization import ClusterOutputMaterializer
from app.domain import (
    AgentRole,
    CandidateCategory,
    CandidateItem,
    ConfidenceLevel,
    EvidenceItem,
    EvidenceStrength,
    RunPhase,
    SignalStatus,
    SourceAccessLevel,
    SourceType,
    TraceEventType,
)
from app.harness import HarnessConfig, HarnessContext
from app.repositories import (
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    RunRepository,
)
from app.services import TraceService
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


def test_cluster_materializer_links_early_signal_to_official_confirmation(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    evidence = _persist_evidence_and_candidates(db_session)

    result = _cluster_result(
        ClusterDraft(
            category=CandidateCategory.CONFIRMED_EVENT,
            title="OpenAI reasoning-control API confirmation",
            canonical_claim=(
                "Official documentation confirms a reasoning-control API surface "
                "that earlier community and code signals pointed toward."
            ),
            candidate_ids=["cand_phase9_early", "cand_phase9_official"],
            evidence_ids=[item.id for item in evidence],
            entities=["OpenAI"],
            topics=["api", "reasoning"],
            timeline=[
                ClusterTimelineDraft(
                    summary="Early signal and official confirmation were linked.",
                    candidate_ids=["cand_phase9_early", "cand_phase9_official"],
                )
            ],
            conflict_summary="The early signal named the field imprecisely; official docs clarify it.",
            dedupe_key="openai:reasoning-control-api",
        )
    )

    materialized = ClusterOutputMaterializer(HarnessContext(db_session, config=HarnessConfig())).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=result,
        bootstrap_evaluations=True,
    )

    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)
    evaluations = EvaluationRepository(db_session).list_by_run(RUN_ID)
    persisted_run = RunRepository(db_session).require(RUN_ID)

    assert materialized.cluster_ids == [clusters[0].id]
    assert clusters[0].category == CandidateCategory.CONFIRMED_EVENT
    assert clusters[0].candidate_ids == ["cand_phase9_early", "cand_phase9_official"]
    assert clusters[0].evidence_ids == ["ev_phase9_social", "ev_phase9_official"]
    assert clusters[0].metadata["confirmation_linked"] is True
    assert clusters[0].metadata["confirmed_prior_signal_candidate_ids"] == ["cand_phase9_early"]
    assert clusters[0].metadata["confirmation_candidate_ids"] == ["cand_phase9_official"]
    assert "bootstrap_single_agent" not in clusters[0].metadata
    assert len(evaluations) == 1
    assert evaluations[0].decision == "select_confirmed"
    assert evaluations[0].metadata["bootstrap_clusterer_evaluation"] is True
    assert persisted_run.cluster_ids == [clusters[0].id]

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert TraceEventType.CLUSTER_CREATED in [event.event_type for event in timeline.events]
    assert TraceEventType.EVALUATION_CREATED in [event.event_type for event in timeline.events]


def test_cluster_materializer_merges_existing_dedupe_key_and_preserves_conflict(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    _persist_evidence_and_candidates(db_session)
    candidate_repo = CandidateRepository(db_session)
    evidence_repo = EvidenceRepository(db_session)
    evidence_repo.add(
        EvidenceItem(
            id="ev_phase9_conflict",
            run_id=RUN_ID,
            source_type=SourceType.GITHUB,
            source_name="GitHub",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.MODERATE,
            url="https://example.com/conflict",
            title="Conflicting SDK reference",
            snippet="A wrapper uses a different parameter name.",
            raw_hash="sha256:phase9-conflict",
            created_at=BASE_TIME,
        )
    )
    candidate_repo.add(
        CandidateItem(
            id="cand_phase9_conflict",
            run_id=RUN_ID,
            category=CandidateCategory.EARLY_SIGNAL,
            signal_status=SignalStatus.CODE_ANOMALY,
            claim_summary="A wrapper names the reasoning-control option differently.",
            entities=["OpenAI"],
            topics=["api", "reasoning"],
            evidence_ids=["ev_phase9_conflict"],
            uncertainty=ConfidenceLevel.MEDIUM,
            evidence_strength=EvidenceStrength.MODERATE,
            followup_questions=["Check which field name appears in first-party SDKs."],
            created_by_agent=AgentRole.CODE_MODEL_SCOUT,
            metadata={"conflicts_with_candidate_ids": ["cand_phase9_official"]},
            created_at=BASE_TIME,
        )
    )

    context = HarnessContext(db_session, config=HarnessConfig())
    materializer = ClusterOutputMaterializer(context)
    first = materializer.materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.CONFIRMED_EVENT,
                title="OpenAI reasoning-control API confirmation",
                canonical_claim="Official docs confirm the API surface.",
                candidate_ids=["cand_phase9_early", "cand_phase9_official"],
                dedupe_key="openai:reasoning-control-api",
            )
        ),
        bootstrap_evaluations=False,
    )
    second = materializer.materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.CONFIRMED_EVENT,
                title="OpenAI reasoning-control API confirmation",
                canonical_claim="Official docs confirm the API surface, with naming still worth tracking.",
                candidate_ids=["cand_phase9_conflict"],
                conflict_summary="One SDK wrapper uses a different parameter name.",
                dedupe_key="openai:reasoning-control-api",
            )
        ),
        bootstrap_evaluations=False,
    )

    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)
    persisted_run = RunRepository(db_session).require(RUN_ID)

    assert first.cluster_ids == second.cluster_ids
    assert len(clusters) == 1
    assert clusters[0].candidate_ids == [
        "cand_phase9_early",
        "cand_phase9_official",
        "cand_phase9_conflict",
    ]
    assert clusters[0].evidence_ids == [
        "ev_phase9_social",
        "ev_phase9_official",
        "ev_phase9_conflict",
    ]
    assert clusters[0].conflict_summary == "One SDK wrapper uses a different parameter name."
    assert clusters[0].metadata["conflict_candidate_ids"] == ["cand_phase9_official"]
    assert persisted_run.cluster_ids == [clusters[0].id]


def test_cluster_materializer_splits_overbroad_official_cluster(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    evidence = [
        EvidenceItem(
            id="ev_anthropic_pricing",
            run_id=RUN_ID,
            source_type=SourceType.OFFICIAL_BLOG,
            source_name="Anthropic Blog",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.OFFICIAL,
            url="https://example.com/anthropic-pricing",
            title="Anthropic updates API pricing",
            published_at=BASE_TIME,
            retrieved_at=BASE_TIME,
            snippet="Official pricing update for an API model.",
            raw_hash="sha256:anthropic-pricing",
            created_at=BASE_TIME,
        ),
        EvidenceItem(
            id="ev_anthropic_benchmark",
            run_id=RUN_ID,
            source_type=SourceType.OFFICIAL_BLOG,
            source_name="Anthropic Blog",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.OFFICIAL,
            url="https://example.com/anthropic-benchmark",
            title="Anthropic publishes a benchmark report",
            published_at=BASE_TIME,
            retrieved_at=BASE_TIME,
            snippet="Official benchmark report for model behavior.",
            raw_hash="sha256:anthropic-benchmark",
            created_at=BASE_TIME,
        ),
    ]
    candidates = [
        CandidateItem(
            id="cand_anthropic_pricing",
            run_id=RUN_ID,
            category=CandidateCategory.OFFICIAL_UPDATE,
            signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
            claim_summary="Anthropic officially updated API pricing.",
            entities=["Anthropic"],
            topics=["api", "pricing"],
            evidence_ids=["ev_anthropic_pricing"],
            uncertainty=ConfidenceLevel.HIGH,
            evidence_strength=EvidenceStrength.OFFICIAL,
            why_it_matters="Pricing changes affect production cost controls.",
            potential_impact="Developers may need to update routing and budgets.",
            created_by_agent=AgentRole.OFFICIAL_SCOUT,
            created_at=BASE_TIME,
        ),
        CandidateItem(
            id="cand_anthropic_benchmark",
            run_id=RUN_ID,
            category=CandidateCategory.OFFICIAL_UPDATE,
            signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
            claim_summary="Anthropic officially published a benchmark report.",
            entities=["Anthropic"],
            topics=["benchmark", "model_report"],
            evidence_ids=["ev_anthropic_benchmark"],
            uncertainty=ConfidenceLevel.HIGH,
            evidence_strength=EvidenceStrength.OFFICIAL,
            why_it_matters="Benchmarks change model-selection expectations.",
            potential_impact="Teams may revisit eval baselines and model routing.",
            created_by_agent=AgentRole.OFFICIAL_SCOUT,
            created_at=BASE_TIME,
        ),
    ]
    EvidenceRepository(db_session).add_many(evidence)
    for candidate in candidates:
        CandidateRepository(db_session).add(candidate)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.OFFICIAL_UPDATE,
                title="Anthropic official updates",
                canonical_claim="Anthropic published several official updates.",
                candidate_ids=[candidate.id for candidate in candidates],
                evidence_ids=[item.id for item in evidence],
            )
        ),
        bootstrap_evaluations=False,
    )

    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)

    assert len(result.cluster_ids) == 2
    assert len(clusters) == 2
    assert {cluster.candidate_ids[0] for cluster in clusters} == {
        "cand_anthropic_pricing",
        "cand_anthropic_benchmark",
    }
    assert all(cluster.metadata["split_overbroad_official_cluster"] is True for cluster in clusters)


def test_cluster_materializer_splits_unrelated_mixed_confirmation_cluster(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    evidence = [
        EvidenceItem(
            id="ev_hf_lerobot",
            run_id=RUN_ID,
            source_type=SourceType.OFFICIAL_BLOG,
            source_name="Hugging Face Blog",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.OFFICIAL,
            url="https://huggingface.co/blog/lerobot-v06",
            title="LeRobot v0.6.0 released",
            published_at=BASE_TIME,
            retrieved_at=BASE_TIME,
            snippet="Hugging Face announces a LeRobot release.",
            raw_hash="sha256:hf-lerobot",
            created_at=BASE_TIME,
        ),
        EvidenceItem(
            id="ev_hn_jj",
            run_id=RUN_ID,
            source_type=SourceType.HACKER_NEWS,
            source_name="Hacker News",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.MODERATE,
            url="https://news.ycombinator.com/item?id=123",
            title="Ask HN: Is anyone using Jujutsu version control exclusively?",
            published_at=BASE_TIME,
            retrieved_at=BASE_TIME,
            snippet="Community discussion about Jujutsu version control.",
            raw_hash="sha256:hn-jj",
            created_at=BASE_TIME,
        ),
    ]
    candidates = [
        CandidateItem(
            id="cand_hf_lerobot",
            run_id=RUN_ID,
            category=CandidateCategory.OFFICIAL_UPDATE,
            signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
            claim_summary="Hugging Face officially announced LeRobot v0.6.0.",
            entities=["Hugging Face", "LeRobot"],
            topics=["robotics"],
            evidence_ids=["ev_hf_lerobot"],
            uncertainty=ConfidenceLevel.HIGH,
            evidence_strength=EvidenceStrength.OFFICIAL,
            why_it_matters="Official release changes robotics tooling expectations.",
            potential_impact="Teams may revisit robot-data workflows.",
            created_by_agent=AgentRole.OFFICIAL_SCOUT,
            created_at=BASE_TIME,
        ),
        CandidateItem(
            id="cand_hn_jj",
            run_id=RUN_ID,
            category=CandidateCategory.EARLY_SIGNAL,
            signal_status=SignalStatus.COMMUNITY_RUMOR,
            claim_summary="HN users are discussing exclusive Jujutsu version-control adoption.",
            entities=["Jujutsu"],
            topics=["version_control"],
            evidence_ids=["ev_hn_jj"],
            uncertainty=ConfidenceLevel.LOW,
            evidence_strength=EvidenceStrength.MODERATE,
            followup_questions=["Check whether tooling adoption grows beyond HN discussion."],
            created_by_agent=AgentRole.SOCIAL_SCOUT,
            created_at=BASE_TIME,
        ),
    ]
    EvidenceRepository(db_session).add_many(evidence)
    for candidate in candidates:
        CandidateRepository(db_session).add(candidate)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                title="Community and official updates",
                canonical_claim="Hugging Face, LeRobot, and Jujutsu all appeared in source updates.",
                candidate_ids=[candidate.id for candidate in candidates],
                evidence_ids=[item.id for item in evidence],
                metadata={"confirmation_linked": True},
            )
        ),
        bootstrap_evaluations=False,
    )

    clusters = EventClusterRepository(db_session).list_by_run(RUN_ID)

    assert len(result.cluster_ids) == 2
    assert len(clusters) == 2
    assert {tuple(cluster.candidate_ids) for cluster in clusters} == {
        ("cand_hf_lerobot",),
        ("cand_hn_jj",),
    }
    assert {cluster.category for cluster in clusters} == {
        CandidateCategory.OFFICIAL_UPDATE,
        CandidateCategory.EARLY_SIGNAL,
    }
    assert all(
        cluster.metadata["split_reason"] == "unrelated_mixed_confirmation_cluster"
        for cluster in clusters
    )


def test_cluster_materializer_repairs_missing_candidate_id_from_evidence(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    _persist_evidence_and_candidates(db_session)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                title="Repaired cluster",
                canonical_claim="This cluster can be repaired from evidence lineage.",
                candidate_ids=["missing_candidate"],
                evidence_ids=["ev_phase9_social"],
            )
        ),
        bootstrap_evaluations=False,
    )

    cluster = EventClusterRepository(db_session).require(result.cluster_ids[0])
    assert cluster.candidate_ids == ["cand_phase9_early"]
    assert cluster.metadata["repaired_candidate_ids"] is True
    assert cluster.metadata["requested_candidate_ids"] == ["missing_candidate"]
    assert cluster.metadata["fallback_candidate_ids_from_run"] is True


def test_cluster_materializer_filters_missing_candidate_ids(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    _persist_evidence_and_candidates(db_session)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                title="Partially repaired cluster",
                canonical_claim="This cluster keeps valid candidate lineage.",
                candidate_ids=["missing_candidate", "cand_phase9_early"],
            )
        ),
        bootstrap_evaluations=False,
    )

    cluster = EventClusterRepository(db_session).require(result.cluster_ids[0])
    assert cluster.candidate_ids == ["cand_phase9_early"]
    assert cluster.metadata["missing_candidate_ids"] == ["missing_candidate"]


def test_cluster_materializer_repairs_missing_evidence_ids_from_candidates(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)
    _persist_evidence_and_candidates(db_session)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                title="Evidence repaired cluster",
                canonical_claim="This cluster keeps verified candidate evidence only.",
                candidate_ids=["cand_phase9_early"],
                evidence_ids=["ev_missing_clusterer_hallucination"],
                timeline=[
                    ClusterTimelineDraft(
                        summary="Clusterer referenced a bad evidence ID.",
                        evidence_ids=["ev_missing_clusterer_hallucination"],
                    )
                ],
            )
        ),
        bootstrap_evaluations=False,
    )

    cluster = EventClusterRepository(db_session).require(result.cluster_ids[0])
    assert cluster.evidence_ids == ["ev_phase9_social"]
    assert cluster.timeline[0].evidence_ids == ["ev_phase9_social"]
    assert cluster.metadata["repaired_evidence_ids"] is True
    assert cluster.metadata["missing_evidence_ids"] == ["ev_missing_clusterer_hallucination"]
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(
        event.summary == "Clusterer draft evidence lineage was repaired before materialization."
        and event.metadata["missing_evidence_ids"] == ["ev_missing_clusterer_hallucination"]
        for event in timeline.events
    )


def test_cluster_materializer_skips_unrepairable_candidate_lineage(db_session) -> None:
    run = run_state_fixture()
    RunRepository(db_session).add(run)

    result = ClusterOutputMaterializer(HarnessContext(db_session)).materialize(
        run=run,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        result=_cluster_result(
            ClusterDraft(
                category=CandidateCategory.EARLY_SIGNAL,
                title="Bad cluster",
                canonical_claim="This cluster references a missing candidate.",
                candidate_ids=["missing_candidate"],
            )
        ),
        bootstrap_evaluations=False,
    )

    assert result.cluster_ids == []
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert any(
        event.summary == "Clusterer draft skipped because candidate lineage could not be repaired."
        and event.metadata["skipped"] is True
        for event in timeline.events
    )


def _cluster_result(draft: ClusterDraft) -> AgentRunResult:
    return AgentRunResult(
        run_id=RUN_ID,
        phase=RunPhase.CLUSTERING,
        agent_role=AgentRole.CLUSTERER,
        structured_output=ClustererOutput(
            summary="Clusterer created cluster drafts.",
            reasoning_summary="Candidates describe the same underlying event.",
            cluster_drafts=[draft],
        ),
    )


def _persist_evidence_and_candidates(db_session) -> list[EvidenceItem]:
    evidence_repo = EvidenceRepository(db_session)
    candidate_repo = CandidateRepository(db_session)
    evidence = [
        EvidenceItem(
            id="ev_phase9_social",
            run_id=RUN_ID,
            source_type=SourceType.REDDIT,
            source_name="Reddit",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.MODERATE,
            url="https://example.com/social",
            title="Community reasoning-control report",
            snippet="Users report a reasoning-control option in API behavior.",
            raw_hash="sha256:phase9-social",
            created_at=BASE_TIME,
        ),
        EvidenceItem(
            id="ev_phase9_official",
            run_id=RUN_ID,
            source_type=SourceType.API_CHANGELOG,
            source_name="API changelog",
            access_level=SourceAccessLevel.PUBLIC,
            strength=EvidenceStrength.OFFICIAL,
            url="https://example.com/official",
            title="Official reasoning-control API docs",
            snippet="Official docs describe a reasoning-control API option.",
            raw_hash="sha256:phase9-official",
            created_at=BASE_TIME,
        ),
    ]
    evidence_repo.add_many(evidence)
    candidate_repo.add(
        CandidateItem(
            id="cand_phase9_early",
            run_id=RUN_ID,
            category=CandidateCategory.EARLY_SIGNAL,
            signal_status=SignalStatus.GRAY_ROLLOUT_FEEDBACK,
            claim_summary="Community reports suggest a reasoning-control API option is being tested.",
            entities=["OpenAI"],
            topics=["api", "reasoning"],
            evidence_ids=["ev_phase9_social"],
            uncertainty=ConfidenceLevel.MEDIUM,
            evidence_strength=EvidenceStrength.MODERATE,
            followup_questions=["Check official API docs."],
            created_by_agent=AgentRole.SOCIAL_SCOUT,
            created_at=BASE_TIME,
        )
    )
    candidate_repo.add(
        CandidateItem(
            id="cand_phase9_official",
            run_id=RUN_ID,
            category=CandidateCategory.CONFIRMED_EVENT,
            signal_status=SignalStatus.OFFICIAL_CONFIRMATION,
            claim_summary="Official docs confirm a reasoning-control API option.",
            entities=["OpenAI"],
            topics=["api", "reasoning"],
            evidence_ids=["ev_phase9_official"],
            uncertainty=ConfidenceLevel.HIGH,
            evidence_strength=EvidenceStrength.OFFICIAL,
            created_by_agent=AgentRole.OFFICIAL_SCOUT,
            created_at=BASE_TIME,
        )
    )
    return evidence
