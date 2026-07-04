# Connor.ai Master Plan

Last updated: 2026-07-04

## 1. Product Intent

Connor.ai is not a simple AI news summarizer. It is a traceable, replayable, reviewable, long-running multi-agent intelligence system for AI, semiconductor, and technology-stock frontier information.

The system should produce a daily intelligence report with:

- `full_markdown`: human-readable daily report.
- `full_json`: structured data for the future dashboard.
- `evidence_map`: evidence lineage behind every report item.
- `watchlist_updates`: short-term tracking changes.
- `trace_timeline`: execution timeline for agent, tool, evaluation, writing, and review actions.

The core design principle is:

```text
Agents may explore freely, but every useful output must land in stable Connor.ai data structures and trace records.
```

## 2. Runtime Split

AgentScope 2.0 is the agent runtime layer. It is responsible for:

- Agent creation and role prompts.
- Tool calls.
- Event stream.
- Middleware.
- Agent team / worker organization.

Connor loop harness is the product control layer. It is responsible for:

- Run state.
- Loop boundaries.
- Quality gates.
- Cost controls.
- Artifact archival.
- Trace persistence.
- Report finalization.

## 3. Agent Topology

```text
Orchestrator
  -> Social Scout
  -> Code & Model Scout
  -> Research Scout
  -> Official Scout
  -> Finance Scout
  -> Clusterer
  -> Evaluator Group
      -> Frontier Evaluator
      -> Event Evaluator
      -> Market Evaluator
  -> Watchlist Agent
  -> Writer
  -> Reviewer
  -> Editor
  -> Reviewer
  -> Final Report
```

Evaluator failure should not flow directly into writing. Failed or incomplete evaluation returns to the collect loop through the evaluation gate.

## 4. Core Loops

### Collect Loop

```text
Orchestrator
-> Scouts
-> Clusterer
-> Evaluators
-> Evaluation Gate
-> followup / recluster / watch / archive / select
```

Evaluation gate decisions:

- `select_confirmed`: include as confirmed event.
- `select_early_signal`: include as early signal with uncertainty label.
- `short_watch`: actively track for a limited period.
- `followup_now`: send back to scouts immediately.
- `followup_later`: defer follow-up with lower cadence.
- `recluster`: send back to clusterer.
- `archive`: stop active tracking but preserve in historical memory.
- `reject`: drop as noise or irrelevant.

### Writing Loop

```text
Selected Items
-> Writer
-> Reviewer
-> Editor
-> Reviewer
-> Final
```

Writing quality failures return to Editor, not to Scout, unless Reviewer identifies a missing-evidence issue that requires reopening the collect loop.

## 5. Early Signal Policy

Early Signals should not be judged by confirmed-event standards.

The system may include low-confidence signals if they are:

- Specific.
- Information-rich.
- Relevant to priority themes.
- Potentially high-impact.
- Trackable.
- Clearly labeled as unconfirmed, gray rollout, code anomaly, researcher hint, or community rumor.

Reviewer must prevent early signals from being written as confirmed facts.

## 6. Watchlist, Archive, and Intelligence Threads

Watchlist is the short-term active tracking pool. It must control cost and avoid unbounded growth.

Watchlist items must include:

- `ttl_days`
- `watch_until`
- `priority`
- `revisit_cadence`
- `last_checked_at`
- `last_signal_at`
- `decay_score`
- `reactivation_rules`
- `status`

Suggested tiers:

```text
Short Watch      3-7 days, leaks, gray rollouts, community signals.
Event Watch      7-21 days, launches, earnings windows, regulatory events.
Strategic Watch  30-90 days, Blackwell, HBM, CoWoS, AI capex, ASIC trends.
Archive          no active tracking, preserved as historical memory.
```

Archive is not deletion. Archived signals become part of long-term historical memory.

Intelligence Threads connect early signals, archives, confirmations, reversals, and later outcomes into a logical chain.

Example:

```text
Thread: OpenAI reasoning-control API evolution
2026-07-03: Community signal appears.
2026-07-04: Third-party SDK reference appears.
2026-07-10: Watch expires and archives.
2026-07-18: Official changelog confirms related API control.
```

This allows future agents to reason over historical signal chains without actively rechecking every old watch item.

## 7. Core Data Structures

- `RunState`
- `EvidenceItem`
- `CandidateItem`
- `EventCluster`
- `EvaluationResult`
- `WatchlistItem`
- `ArchivedSignal`
- `IntelligenceThread`
- `DailyReport`
- `TraceEvent`
- `Artifact`
- `ToolCallRecord`
- `ModelCallRecord`

## 8. Development Phases

### Phase 1: Domain Schemas

Define the system language before agents, tools, or databases.

Acceptance:

- Stable JSON serialization.
- Complete enums.
- Fixtures for each schema.
- Unit tests.
- No dependency on database or AgentScope.

### Phase 2: Database Persistence

Persist core objects in PostgreSQL.

Tables:

- `runs`
- `evidence_items`
- `candidate_items`
- `event_clusters`
- `evaluation_results`
- `watchlist_items`
- `archived_signals`
- `intelligence_threads`
- `daily_reports`
- `trace_events`
- `tool_calls`
- `model_calls`
- `artifacts`

Acceptance:

- Alembic can create schema from an empty database.
- Repository tests pass.
- Full run state can be reconstructed.
- Thread history can be queried.

### Phase 3: Tracing and Artifacts

Build replayable execution records.

Acceptance:

- Run timeline can be replayed.
- Report entries can trace back to evidence and trace events.
- Large payloads are stored as artifacts.
- No full chain-of-thought is stored.

### Phase 4: Tool Contract and Registry

Build standardized tool interfaces before broad source expansion.

Unified tool envelope:

```json
{
  "tool_name": "...",
  "source_type": "...",
  "query": "...",
  "retrieved_at": "...",
  "items": [],
  "errors": [],
  "rate_limit": {},
  "raw_artifact_ref": "..."
}
```

Acceptance:

- Any tool output can normalize to `EvidenceItem`.
- Tool failure does not break a run.
- Tool calls automatically trace.
- Registry can assign tools by agent role.

### Phase 5: AgentScope Integration

Connect AgentScope without hiding business state in prompts or creating a separate Connor agent runtime.

Acceptance:

- AgentScope is a main dependency.
- AgentRunner directly creates and invokes AgentScope `Agent`.
- Connor tools are exposed through AgentScope `Toolkit` / `FunctionTool`.
- Agent output schemas validate.
- Tool calls trace automatically.
- Agent failures are recoverable.
- Different agents have different tool sets.

### Phase 6: Loop Harness

Implement collect and writing state machines with boundaries.

Acceptance:

- DailyRunHarness can create, run, and resume daily runs.
- Collect loop can enter writing, follow up, recluster, continue, pause for manual review, or fail.
- Writing loop can review, revise, reopen collection, finalize, pause for manual review, or fail.
- Max rounds, budgets, and revision limits prevent infinite loops.
- Harness gate decisions are persisted as trace events.
- Gate and final-report snapshots are stored as artifacts.

### Phase 7: Single-Agent Closed Loop

Make one scout fully reliable before scaling to all agents.

Acceptance:

- Create run.
- Assign task.
- Call tool.
- Create evidence.
- Create candidate.
- Materialize candidate through Connor boundary, not direct agent DB writes.
- Create marked provisional cluster/evaluation only when no explicit Clusterer/Evaluator task exists.
- Collect gate can enter writing from the single-agent generated item.
- Write trace.
- Persist all outputs.

### Phase 8: All Scouts

Complete:

- Social Scout
- Code & Model Scout
- Research Scout
- Official Scout
- Finance Scout

Acceptance:

- Each Scout has a `ScoutProfile`.
- Each Scout has source-type, candidate-category, signal-status, follow-up, and focus-topic boundaries.
- Official Scout requires strong or official evidence-strength claims.
- Finance Scout requires ticker or impact-chain relevance.
- AgentScope role prompts include Scout profile constraints.
- `ScoutTaskFactory` can create all five role-specific Scout tasks with profile context.
- `ScoutOutputMaterializer` validates Scout outputs before candidate persistence.
- All five Scouts can run through AgentScope tool calls and produce materialized candidates.
- Invalid Scout output is rejected before persistence.

### Phase 9: Clusterer

Merge candidates into event clusters.

Acceptance:

- Deduplication works.
- Conflicting evidence is preserved.
- Canonical claim is generated.
- Early signals and later official confirmations can be linked.
- Clusterer has a role-specific `ClustererOutput` schema.
- Clusterer outputs are materialized by Connor, not written directly by agents.
- Dedupe-key merges preserve candidate and evidence lineage.
- The collect loop passes candidate context into Clusterer tasks.
- A temporary marked evaluator bridge keeps the loop runnable until Phase 10.

### Phase 10: Evaluator Group

Implement:

- Frontier Evaluator
- Event Evaluator
- Market Evaluator

Acceptance:

- Evaluator agents return structured `EvaluationDraft` records through AgentScope.
- Connor materializes evaluator drafts into `EvaluationResult` records.
- Frontier/Event/Market evaluator profiles define allowed categories, decisions, and score dimensions.
- Early signal standards are intentionally looser than confirmed-event standards.
- Confirmed-event selection requires no missing evidence and sufficient score.
- Market evaluation requires AI relevance, market impact, supply-chain impact, and ticker relevance.
- Collect loop injects cluster context into evaluator tasks.
- Evaluator decisions write trace events and drive collect-gate outcomes.

### Phase 11: Watchlist, Archive, and Intelligence Threads

Implement cost-aware memory.

Acceptance:

- Watchlist Agent returns structured watchlist, archive, and thread drafts.
- Connor materializes those drafts into `WatchlistItem`, `ArchivedSignal`, and `IntelligenceThread`.
- Watch items expire through deterministic lifecycle policy.
- Expired items archive without deleting historical state.
- Evaluator decisions can create default memory when no Watchlist Agent task is scheduled.
- Archive records preserve lineage and reactivation hints.
- Threads show historical evolution across signals, watches, archives, confirmations, and later outcomes.
- Collect loop injects memory context into Watchlist Agent tasks.

### Phase 12: Writing Loop

Produce and review the daily report.

Acceptance:

- `full_markdown`, `full_json`, `evidence_map`, `watchlist_updates`, and `trace_timeline` are generated.
- Reviewer prevents uncertain signals from being written as facts.
- Markdown and JSON are consistent.

### Phase 13: FastAPI and Dashboard Contract

Expose stable API.

Endpoints:

- `POST /runs/daily`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/trace`
- `GET /runs/{run_id}/clusters`
- `GET /reports/{report_id}`
- `GET /watchlist`
- `GET /threads`
- `GET /threads/{thread_id}`

### Phase 14: Source Expansion

Expand sources after the system core is reliable.

Suggested order:

1. GitHub / Hugging Face
2. arXiv / OpenReview
3. Official blogs / changelogs
4. SEC / IR / earnings
5. HN / Reddit
6. X / Twitter
7. Paid finance and semiconductor sources

## 9. Documentation Rule

Every implementation step must update the project archive:

- What was done.
- Why it was done.
- Files changed.
- Tests or checks run.
- Result achieved.
- Open questions or follow-ups.

The canonical archive files are:

- `docs/MASTER_PLAN.md`
- `docs/PROGRESS.md`
- `docs/DEV_LOG.md`
- `docs/adr/`
- `docs/plans/`
- `docs/logs/`
