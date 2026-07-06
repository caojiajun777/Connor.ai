# Worklog: Phase 15A Report Quality and Selection Hardening

Date: 2026-07-05

Status: Complete

## Part 1: Live Run Quality Review

### Used

- Real DeepSeek AgentScope smoke run.
- Real public-source tools through Connor `ToolExecutor`.
- SQLite run database `connor_quality_review.db`.
- Local report, review, evidence, cluster, evaluation, and trace records.

### Did

- Re-ran a formal daily cycle to inspect business output quality.
- Read the generated run, report, review results, clusters, evaluations, tool calls, and evidence records.
- Compared the report against Connor.ai's intended product structure.

### How

- Started the strict full daily-cycle smoke run with `CONNOR_DATABASE_URL=sqlite:///./connor_quality_review.db`.
- Queried persisted records directly from SQLite.
- Checked whether the run finalized, whether the report passed review, and whether selected content covered Early Signals, Confirmed Events, and Tech-Finance.

### Problems and Solutions

- Problem: The smoke test passed even though the run ended as `paused / reviewing`.
  - Solution: Planned and implemented stricter smoke assertions requiring finalized run and final report status.
- Problem: The report focused on one research cluster while official and finance clusters were collected but omitted.
  - Solution: Added deterministic report bucket coverage in the collect gate.
- Problem: Reviewer issues were valid but the loop exhausted revision budget.
  - Solution: Added deterministic finalization checks so missing selected clusters and missing report buckets are blocked before false finalization.

## Part 2: Selection Coverage Hardening

### Used

- `QualityGateService`.
- `HarnessConfig`.
- Persisted `EventCluster` and `EvaluationResult` records.
- Existing evaluator decisions and candidate categories.

### Did

- Added report bucket definitions for Early Signals, Confirmed Events, and Tech-Finance.
- Added writeable follow-up decisions to collect-gate selection.
- Preserved explicit evaluator selections while adding one writeable cluster from missing required buckets.
- Marked all selected clusters as selected when the collect loop enters writing.

### How

- Kept `SELECT_CONFIRMED` and `SELECT_EARLY_SIGNAL` as explicit selections.
- Treated `FOLLOWUP_NOW`, `FOLLOWUP_LATER`, and `SHORT_WATCH` as writeable with caveat when used for available official or finance buckets.
- Added metadata and metrics showing available and selected bucket counts.
- Updated collect-loop application so gate-selected clusters are persisted with `selected=True`.

### Problems and Solutions

- Problem: The old collect gate equated "follow-up needed" with "not writeable."
  - Solution: The gate now separates "needs caveat/follow-up" from "should disappear from report."
- Problem: Existing tests assumed a pass review only needed any report artifact.
  - Solution: Updated fixtures and tests to include tomorrow-focus and selected-cluster coverage requirements.

## Part 3: Writer Contract and Finalization Gate

### Used

- `WritingTaskFactory`.
- `QualityGateService.evaluate_writing`.
- `DailyReport`, `ReportItem`, and report `full_json`.

### Did

- Added a `report_quality_contract` to writer context.
- Added `report_bucket`, `write_policy`, `required_followups`, and `missing_evidence` to selected cluster summaries.
- Blocked finalization if selected clusters are missing from report items.
- Blocked finalization if selected buckets are missing from report items.
- Blocked finalization if `tomorrow_focus` is missing.

### How

- Derived writer buckets from selected cluster categories.
- Derived write policy from evaluator decisions:
  - `write_now`
  - `write_with_caveat`
  - `archive_or_note_exclusion`
  - `do_not_write`
  - `context_only`
- Compared selected cluster ids against report item cluster ids during writing gate evaluation.

### Problems and Solutions

- Problem: Writer could ignore selected official or finance clusters without a deterministic failure.
  - Solution: Finalization now fails with `missing_selected_cluster:<id>` and `missing_report_bucket:<bucket>`.
- Problem: A report could omit next-day focus while still passing structural checks.
  - Solution: `missing_tomorrow_focus` is now a finalization blocker.

## Part 4: Tests and Verification

### Used

- Pytest.
- Ruff.
- Existing domain fixtures.
- New writer context tests.

### Did

- Added collect gate coverage tests.
- Added writing gate finalization-blocker tests.
- Added writer context contract tests.
- Hardened the live full-cycle smoke test so paused or needs-revision runs fail.

### How

- Created fixtures where official and finance clusters have `FOLLOWUP_NOW` evaluations and must still enter writing.
- Added assertions that selected official/finance clusters are included in `selected_cluster_ids`.
- Added assertions that smoke output requires `RunPhase.FINALIZED`, `RunStatus.COMPLETED`, and `ReportStatus.FINAL`.

### Problems and Solutions

- Problem: The existing report fixture did not include `tomorrow_focus` in `full_json`.
  - Solution: Updated the fixture to match the new final report requirements.

## Part 5: Reviewer Runtime Robustness

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `AgentRunner` structured-output normalization.
- `WritingTaskFactory.reviewer_context`.
- Reviewer output schema tests.

### Did

- Investigated the first strict live smoke failure after report-quality hardening.
- Found that Reviewer context exceeded practical size and triggered AgentScope context compression.
- Found that Reviewer sometimes emitted issue objects in a non-schema shape after compression.
- Added deterministic Reviewer issue normalization.
- Replaced Reviewer full-state context with a compact review summary.

### How

- Read smoke stdout/stderr and the failing Pydantic validation path.
- Normalized malformed review issues into `priority`, `title`, and `body` while preserving metadata.
- Added a fallback Reviewer summary when the model omits top-level `summary`.
- Built Reviewer context from report items, selected clusters, reported cluster ids, missing selected cluster ids, relevant evidence summaries, and recent trace ids only.

### Problems and Solutions

- Problem: Reviewer output repair could still fail when issue objects only contained unknown fields such as `problem` and `fix`.
  - Solution: Added deterministic issue-shape repair before Pydantic validation.
- Problem: Reviewer received full evidence and cluster payloads, causing token pressure in formal runs.
  - Solution: Reviewer context now contains compact, review-specific summaries instead of full run dumps.
- Problem: Missing selected-cluster coverage was implicit and hard for Reviewer to detect.
  - Solution: Reviewer context now includes `missing_selected_cluster_ids` directly.

## Part 6: Revision State Refresh

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Persisted review issues and report records.
- `WritingLoopHarness`.
- Writing-loop regression tests.

### Did

- Investigated why the strict smoke still paused after Reviewer schema robustness was fixed.
- Confirmed the run no longer failed from malformed structured output.
- Found that Final Reviewer was reviewing the pre-edit `FullRunState`.
- Refreshed persisted run state immediately after Editor materialization and before Final Review.

### How

- Read the failed smoke result and persisted review issues from the SQLite run database.
- Compared Reviewer findings against the report revision path.
- Added a regression assertion that Final Reviewer sees the revised report status label.
- Updated the writing loop to call `get_full_state()` after `EDITING` completes.

### Problems and Solutions

- Problem: The writing loop reused a stale `full_state` object after Editor changed the report.
  - Solution: Refresh `full_state` after editing and pass the revised report context into Final Review.
- Problem: Existing tests only checked call order, not what report version the Final Reviewer saw.
  - Solution: Added a test assertion over the final review context's report item status label.

## Part 7: Aggregated Reviewer Decisions

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Persisted `review_results`.
- `WritingOutputMaterializer`.
- Review materialization regression tests.

### Did

- Audited the first passing strict smoke run instead of accepting it at face value.
- Found that one Reviewer output could materialize multiple `ReviewResult` rows for the same report.
- Found that mixed `revise` and `pass` rows could let the writing gate finalize by reading the latest `pass`.
- Changed Reviewer materialization to aggregate one Reviewer output into one review result per report.

### How

- Queried the smoke run database after the pass.
- Compared selected cluster coverage, report items, review decisions, and writing gate metadata.
- Added an aggregate decision rule: `reject` > `reopen_collect` > `revise` > `pass`.
- Preserved all review issues and required changes inside the single aggregate review result.

### Problems and Solutions

- Problem: Multiple cluster-level review drafts could become multiple review rows, making result order affect finalization.
  - Solution: Materialize one aggregate review row per report for each Reviewer output.
- Problem: Existing tests did not cover mixed pass/revise review drafts.
  - Solution: Added a regression test requiring mixed drafts to produce one `revise` result.

## Part 8: Watchlist Lineage Boundary

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `WritingOutputMaterializer` lineage validation.
- `QualityGateService` final report coverage checks.
- Watchlist report item regression tests.

### Did

- Investigated a formal run failure where Writer produced a `watchlist_update` report item that referenced event clusters.
- Allowed watchlist update items to cite event clusters as lineage.
- Kept ordinary Early/Confirmed/Finance item lineage strict.
- Tightened selected-cluster coverage so watchlist items do not count as body-section coverage.

### How

- Skipped automatic category normalization for `CandidateCategory.WATCHLIST_UPDATE`.
- Allowed watchlist update items to reference clusters with different event categories.
- Changed the writing gate to count selected cluster coverage only when the item bucket matches the cluster bucket.
- Added tests for both allowed watchlist lineage and disallowed watchlist-only body coverage.

### Problems and Solutions

- Problem: Watchlist items are not event clusters, but they still need lineage back to event clusters.
  - Solution: Permit cross-category cluster links only for `watchlist_update`.
- Problem: A watchlist summary could otherwise satisfy selected-cluster coverage without a real Early/Confirmed/Finance body item.
  - Solution: Finalization coverage now requires bucket-aligned report items.
- Problem: Older harness tests omitted persisted cluster context.
  - Solution: Updated fixtures to persist the selected bundle before category-aware gate checks.

## Part 9: Writer Deterministic Fallback

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `AgentRunner` deterministic fallback path.
- `WritingTaskFactory.writer_context`.
- Writer fallback regression tests.

### Did

- Investigated a formal run failure where Writer produced malformed large JSON even after structured-output repair.
- Added a deterministic Writer fallback after two failed JSON/validation attempts.
- The fallback builds a conservative report draft directly from selected clusters, evidence ids, evaluator decisions, and required follow-ups.

### How

- Extended `AgentRunner._deterministic_structured_fallback()` to support `WriterOutput`.
- Grouped selected clusters into Early Signals, Confirmed Events, and Tech-Finance sections.
- Generated report items with exact cluster/evidence ids, caveat-oriented status labels, follow-up points, overview judgments, and tomorrow focus.
- Marked fallback artifacts with `metadata.deterministic_fallback = true` and trace metadata.

### Problems and Solutions

- Problem: A long Writer JSON response can fail parsing twice because of a small syntax error.
  - Solution: After model repair fails, use selected structured context to produce a valid conservative draft.
- Problem: Fallback output must not invent evidence.
  - Solution: It only copies `evidence_ids` and `cluster_ids` already present in `writing_context.selected_clusters`.

## Part 10: Watchlist Evidence Scope

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `WritingOutputMaterializer._validate_item_lineage`.
- Watchlist materialization regression tests.

### Did

- Investigated a formal run failure where a watchlist item cited evidence that belonged to the run but not to the item's cited cluster.
- Kept strict evidence-to-cluster linkage for normal report items.
- Allowed `watchlist_update` items to cite any evidence belonging to the same run.

### How

- Changed evidence lineage validation to skip the cluster-evidence membership check only for `CandidateCategory.WATCHLIST_UPDATE`.
- Continued requiring every cited evidence id to exist and belong to the current run.
- Added a regression test where a watchlist item references an early-signal cluster but cites official-event evidence from the same run.

### Problems and Solutions

- Problem: Watchlist summaries can legitimately combine evidence from several threads or clusters.
  - Solution: Treat watchlist evidence as run-scoped rather than cluster-scoped.
- Problem: Relaxing evidence validation globally would allow hallucinated lineage.
  - Solution: The relaxation is limited to `watchlist_update`; all other report items remain cluster-scoped.

## Part 11: Watchlist Invalid Draft Skipping

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `WatchlistOutputMaterializer`.
- Watchlist materialization trace events.

### Did

- Investigated a formal run failure where Watchlist Agent produced an `archive_draft` with a non-existent `original_cluster_id`.
- Changed watchlist, archive, and thread draft materialization to skip invalid drafts instead of failing the run.
- Added trace events for skipped drafts.

### How

- Wrapped each watchlist/archive/thread draft materialization in a `HarnessError` catch.
- Recorded a failed `AGENT_DECISION` trace with draft type, serialized draft, and error message.
- Continued materializing any other valid drafts in the same Watchlist Agent output.

### Problems and Solutions

- Problem: A hallucinated watchlist/archive/thread id should not terminate the daily run.
  - Solution: Invalid Watchlist Agent drafts are now skipped and traceable.
- Problem: Silent skipping would hide model quality issues.
  - Solution: Every skipped draft emits a trace event with `metadata.skipped = true`.

## Part 12: Reviewer Markdown Context and Formal Budget

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `WritingTaskFactory.reviewer_context`.
- `RunBudgets` defaults and CLI formal run settings.

### Did

- Investigated a strict smoke run that paused after two review requests.
- Found Reviewer treated the deliberately shortened `full_markdown_excerpt` context field as if the actual report markdown were truncated.
- Removed the markdown excerpt from Reviewer context and replaced it with availability and length metadata.
- Aligned the smoke writing budget with the formal CLI/default budget of three writing rounds.

### How

- Replaced `full_markdown_excerpt` with `full_markdown_available` and `full_markdown_length`.
- Added a regression assertion that Reviewer context does not expose `full_markdown_excerpt`.
- Changed the full-cycle smoke run budget from `max_writing_rounds=2` to `max_writing_rounds=3`.

### Problems and Solutions

- Problem: Context truncation markers looked like report defects to the Reviewer.
  - Solution: Do not provide truncated markdown as a review artifact; review the structured report instead.
- Problem: The smoke test used a tighter writing budget than formal Connor runs.
  - Solution: Use three writing rounds, matching `RunBudgets` default and CLI behavior.

## Part 13: Reviewer Reject Semantics

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `AgentRunner` Reviewer payload normalization.
- Reviewer structured-output regression tests.

### Did

- Investigated a run where Reviewer returned `reject` while also saying the report had actionable issues requiring revision before publication.
- Normalized actionable `reject` decisions into `revise`.
- Preserved the original decision in metadata for traceability.

### How

- If a review draft has decision `reject` but includes issues or required changes, it is converted to `revise`.
- If the top-level Reviewer decision is `reject` but any child draft requires revision, the top-level decision is converted to `revise`.
- Added a regression test for this exact shape.

### Problems and Solutions

- Problem: The model sometimes uses "reject" colloquially to mean "not publishable yet."
  - Solution: Treat actionable reject as revise so the Editor loop can fix it.
- Problem: We still need to know the model originally said reject.
  - Solution: Store `normalized_decision_from = reject` in metadata.

## Part 14: Finance Scout Signal Status Normalization

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Finance Scout profile validation.
- Scout output materialization tests.

### Did

- Investigated a formal run failure where Finance Scout treated official IR/SEC-style evidence as `official_confirmation`.
- Kept the Finance Scout profile narrow and normalized that status to the finance-domain `confirmed_fact`.
- Preserved the original model status in candidate metadata.

### How

- Updated `ScoutOutputMaterializer._normalize_draft_for_profile`.
- When `finance_scout` emits `official_confirmation`, the persisted candidate now uses `confirmed_fact`.
- Added a regression test that runs Finance Scout through the tool, evidence, candidate, profile, and collect loop path.

### Problems and Solutions

- Problem: `official_confirmation` is semantically reasonable for official financial sources but not part of the Finance Scout profile.
  - Solution: Normalize it at the materialization boundary instead of broadening the profile.
- Problem: Normalization could hide model drift.
  - Solution: Store `normalized_signal_status_from` and `normalized_signal_status_reason` in metadata.

## Part 15: Formal Run Timeout and Scout Fault Tolerance

### Used

- Strict DeepSeek full daily-cycle smoke run.
- `AgentRunner` timeout support.
- `CollectLoopHarness` Scout execution path.

### Did

- Investigated a strict smoke run that stopped producing progress while several Scout agents hit the AgentScope max-iteration boundary.
- Added a formal default Agent timeout to role registry construction.
- Allowed Scout-level AgentScope execution failures to be skipped and traced without failing the whole daily run.

### How

- Added `CONNOR_AGENT_TIMEOUT_SECONDS` through runtime settings with a default of 180 seconds.
- Passed the configured timeout into every default `AgentExecutionConfig`.
- Added `HarnessConfig.continue_on_scout_agent_error`.
- Caught only `AgentScopeExecutionError` during the Scout phase; materialization, profile, database, and code errors still raise.
- Added tests for registry timeout wiring, Scout failure continuation, and fail-fast opt-out.

### Problems and Solutions

- Problem: A single real model/API call could hold the whole formal daily run indefinitely.
  - Solution: Default every AgentScope role to a bounded timeout.
- Problem: One Scout source failure should not erase all other collected intelligence.
  - Solution: Scout AgentScope execution errors are traced and skipped; later gates decide whether enough material remains.
- Problem: Broad exception handling would hide product bugs.
  - Solution: The continuation path catches only `AgentScopeExecutionError`.

## Part 16: DeepSeek Client Timeout Wiring

### Used

- Strict DeepSeek full daily-cycle smoke run.
- AgentScope `DeepSeekChatModel` constructor inspection.
- Model factory unit tests.

### Did

- Found that an outer `asyncio.wait_for` is not sufficient protection if the provider call waits inside the model client.
- Wired the role timeout into AgentScope's DeepSeek client kwargs.
- Added a unit test that constructs a DeepSeek model without making a network call and verifies the timeout is passed through.

### How

- Inspected `DeepSeekChatModel.__init__` and confirmed `client_kwargs` is forwarded to `openai.AsyncClient`.
- Updated `create_deepseek_model_factory` to pass `client_kwargs={"timeout": float(config.execution.timeout_seconds)}` when a role timeout is configured.
- Kept the existing outer `AgentRunner` timeout as a second layer.

### Problems and Solutions

- Problem: `asyncio.wait_for` can be too far from the real network wait.
  - Solution: Push timeout into the model provider client itself.
- Problem: A live API test would be slow and flaky for this behavior.
  - Solution: Unit-test the constructed model's `client_kwargs` instead.

## Part 17: Non-Streaming DeepSeek Formal Runs

### Used

- Strict DeepSeek full daily-cycle smoke run.
- AgentScope `DeepSeekChatModel` implementation.
- DeepSeek single-call smoke test.

### Did

- Investigated why provider-client timeout still did not give a clean progress boundary during full formal runs.
- Found that AgentScope's DeepSeek model defaults to streaming responses.
- Changed Connor's DeepSeek factory to use non-streaming responses for formal structured Agent runs.

### How

- Set `stream=False` when constructing `DeepSeekChatModel`.
- Kept provider-client timeout wiring and outer AgentRunner timeout.
- Extended the model factory test to assert non-streaming mode.
- Ran the DeepSeek single-call smoke test to confirm the factory still works against the real provider.

### Problems and Solutions

- Problem: Streaming is useful for UI token display, but Connor's agents need complete structured JSON objects.
  - Solution: Disable streaming for the backend daily-run agent path.
- Problem: We needed confidence that this still works with AgentScope's DeepSeek integration.
  - Solution: Ran the existing DeepSeek smoke test after the change.

## Part 18: Finance Scout Leak Status Boundary

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Finance Scout profile validation.
- Scout closed-loop materialization tests.

### Did

- Investigated a formal run failure where Finance Scout used `unconfirmed_leak` for a tech-finance candidate.
- Generalized Finance Scout status normalization into an explicit mapping.
- Kept official financial claims as `confirmed_fact`, while rumor-like statuses become `single_source_signal`.

### How

- Added `FINANCE_SIGNAL_STATUS_NORMALIZATIONS`.
- Mapped `official_confirmation` to `confirmed_fact`.
- Mapped `unconfirmed_leak`, `gray_rollout_feedback`, `code_anomaly`, `researcher_hint`, and `community_rumor` to `single_source_signal`.
- Added a closed-loop regression test for `unconfirmed_leak`.

### Problems and Solutions

- Problem: The model may use frontier-intelligence status labels in the finance domain.
  - Solution: Normalize those labels at the Finance materialization boundary.
- Problem: Mapping every finance status issue to confirmed fact would overstate weak signals.
  - Solution: Only official confirmation becomes confirmed fact; other non-finance statuses stay cautious as single-source signals.

## Part 19: Clusterer Timeout Deterministic Fallback

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Existing Clusterer deterministic fallback path.
- AgentRunner timeout tests.

### Did

- Investigated a formal run failure where Clusterer exceeded the configured Agent timeout.
- Extended the existing deterministic structured fallback to timeout failures.
- Kept timeout trace records while allowing safe Clusterer fallback output to continue the run.

### How

- In `AgentRunner`, the `asyncio.TimeoutError` branch now records the timeout and then asks `_deterministic_structured_fallback` for a role-safe payload.
- For Clusterer, fallback groups candidate context by category and leading ticker/entity/topic.
- Returned a normal `AgentRunResult` with `timeout_fallback=true` and `deterministic_structured_fallback=true`.
- Added a regression test where Clusterer times out and still returns a deterministic cluster.

### Problems and Solutions

- Problem: Clusterer is important, but its safest fallback is straightforward because all candidates and evidence already exist.
  - Solution: Use one conservative deterministic grouping path instead of failing the daily run.
- Problem: Timeout fallback should not erase the fact that the model timed out.
  - Solution: Keep a failed `ERROR` trace event and add fallback metadata on the completion event.

## Part 20: Tech-Finance Report Item Field Repair

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Writing output materialization.
- Tech-finance report item domain validation.

### Did

- Investigated a writing-stage failure where a Writer item was normalized to `tech_finance` after draft validation but lacked tickers and `potential_impact`.
- Added a materialization repair step after category normalization and lineage validation.
- Added tests for ticker inheritance and conservative impact-chain fallback.

### How

- If a report item is `tech_finance` and has no tickers or impact text, the materializer first inherits tickers from cited clusters.
- If cited clusters also have no tickers, the materializer creates a cautious `potential_impact` from the cited cluster claim.
- The repair happens before constructing the final `ReportItem`, so domain validation still remains strict.

### Problems and Solutions

- Problem: `ReportItemDraft` can pass validation before cluster-based category normalization changes it into `tech_finance`.
  - Solution: Repair required finance fields after normalization, not only at model-output validation time.
- Problem: Inventing ticker symbols would be unsafe.
  - Solution: Only inherit tickers from cluster lineage; otherwise produce a follow-up-oriented impact statement.

## Part 21: Clusterer Candidate Lineage Repair

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Clusterer output materialization.
- Trace schema validation.

### Did

- Investigated a Clusterer failure where the model returned candidate IDs that did not exist in the run.
- Added candidate lineage repair before cluster creation.
- Added tests for evidence-based repair, partial filtering, and unrepairable-draft skipping.

### How

- Valid candidate IDs are kept.
- Missing or wrong-run candidate IDs are recorded in cluster metadata.
- If all candidate IDs are invalid, the materializer tries to recover candidates by evidence overlap, then category match.
- If no safe recovery is possible, the draft is skipped with a failed trace event that includes an error string.

### Problems and Solutions

- Problem: Accepting invented candidate IDs would break replayability and evidence lineage.
  - Solution: Never persist invented candidate IDs; repair only from persisted run candidates.
- Problem: Hard-failing on one bad Clusterer draft stops the entire daily run.
  - Solution: Skip unrecoverable drafts and trace the skip.

## Part 22: Strict Smoke Runtime Observation

### Used

- Strict DeepSeek full daily-cycle smoke run.
- Test output logs under `test_tmp`.
- Windows process monitoring.

### Did

- Re-ran the full daily-cycle smoke after Clusterer candidate-lineage repair.
- Observed that the run no longer failed immediately at the previous Clusterer lineage point.
- Terminated the smoke after an extended period with no new phase output.

### How

- Started `tests/smoke/test_full_daily_cycle.py` with `CONNOR_AGENT_TIMEOUT_SECONDS=60`.
- Monitored the Python process and smoke logs.
- Confirmed repeated Scout ReAct max-iteration warnings and long periods without visible phase progress.
- Stopped the process manually to avoid leaving a runaway live API test.

### Problems and Solutions

- Problem: The formal run path is now reaching deeper stages, but live smoke cost and observability are too high for efficient iteration.
  - Solution: Make the next task runtime-focused: reduce unnecessary ReAct loops, add clearer per-agent progress traces, and tune role-specific timeouts before continuing repeated full smoke runs.
- Problem: A long smoke without progress can hide where the system is spending time.
  - Solution: Treat phase/agent progress visibility as part of Phase 15A quality, not a later operational nicety.

## Part 23: Role Runtime Limits and Task Progress Tracing

### Used

- Agent role registry.
- Collect and writing loop harnesses.
- Scout task construction.

### Did

- Reduced default AgentScope iteration budgets by role.
- Added harness-level task progress trace events for collect and writing phases.
- Tightened Scout tool-use policy to at most one source-tool round unless the first tool fails.

### How

- Scouts now default to `max_iters=2` and `max_tool_calls=1`.
- Clusterer, Evaluators, Watchlist Agent, Writer, Reviewer, and Editor default to `max_iters=1` and `max_tool_calls=0`.
- Collect and writing loops now record task-progress trace events before and after every Agent task.
- Progress events include task index, task count, role, duration, and tool-call count.
- Added regression tests for role execution limits and task-progress trace emission.

### Problems and Solutions

- Problem: Most formal-run time was spent in repeated ReAct iterations before the model returned structured JSON.
  - Solution: Make the default runtime budget match each role's job: Scouts can use tools, downstream roles should produce structured output directly.
- Problem: Long smoke runs did not reveal which role was currently consuming time.
  - Solution: Add per-task progress trace events and durations.

## Part 24: Scout ReAct Boundary Fallback

### Used

- AgentScope runner output handling.
- Connor tool evidence captured by `AgentScopeToolBridge`.
- Scout output schema and role profile constraints.

### Did

- Added a deterministic Scout fallback when AgentScope reaches the ReAct iteration boundary after collecting tool evidence.
- Reduced Scout tool calls to one source-tool round by default for formal runs.
- Added regression coverage for the ReAct-boundary path.

### How

- When AgentScope returns its maximum-iteration message for a Scout, the runner now inspects already persisted tool evidence.
- If evidence exists, Connor builds one conservative `ScoutOutput` candidate draft from that evidence, with role-specific category and status mapping.
- If no evidence exists, Connor returns an empty Scout output with a follow-up query rather than inventing a candidate.
- The fallback records an `AGENT_DECISION` trace event with `repair_mode=deterministic_scout_fallback`.
- Completion metadata now marks both `react_max_iters_repaired=true` and `deterministic_structured_fallback=true`.

### Problems and Solutions

- Problem: Scouts could successfully call a source tool, then spend the remaining ReAct budget trying to produce JSON and return only AgentScope's max-iteration message.
  - Solution: Treat collected evidence as the durable boundary between AgentScope and Connor. If the model does not finish structured output, the harness creates a conservative, traceable Scout draft from persisted evidence.
- Problem: Allowing two tool rounds often doubled runtime without materially improving a formal daily run.
  - Solution: Default Scouts to one source-tool call and let follow-up collection loops decide whether another Scout pass is warranted.

### Verification

- Targeted live Social Scout smoke used `max_iters=2`, `max_tool_calls=1`, and `timeout=45`.
- It completed in 22.66 seconds with 1 tool result, 1 evidence ID, and 1 candidate draft.
- The run returned structured JSON directly, so the deterministic fallback was not needed on that attempt.

## Part 25: Clusterer Evidence Lineage Repair

### Used

- Full-cycle smoke failure traceback.
- Clusterer output materialization.
- Persisted candidate and evidence repositories.

### Did

- Hardened Clusterer materialization against hallucinated or stale evidence IDs.
- Added a regression test for cluster drafts that cite missing evidence but have valid candidate evidence.

### How

- Cluster drafts now validate evidence IDs against persisted run evidence before creating an `EventCluster`.
- Materialization keeps verified draft evidence and candidate evidence, and drops missing or wrong-run evidence IDs.
- If a timeline entry cites invalid evidence, it is rewritten to the cluster's verified evidence IDs.
- Evidence repair metadata is stored on the cluster and a trace event records the repair decision.

### Problems and Solutions

- Problem: A formal smoke run reached clustering, but the Clusterer cited an evidence ID that did not exist in the database.
  - Solution: Treat Clusterer evidence IDs as suggestions, then repair them from candidate lineage before persistence.
- Problem: Direct `require()` calls made one bad evidence ID crash the whole run.
  - Solution: Validate all IDs first, drop invalid IDs when valid candidate lineage exists, and only fail if no verified evidence remains.

## Part 26: Mixed-Category Report Item Repair

### Used

- Full-cycle smoke failure traceback.
- Writing output materialization.
- Persisted cluster categories and evidence lineage.

### Did

- Hardened report item materialization when Writer produces a single item that cites clusters from multiple categories.
- Added a regression test for a mixed Early Signal + Tech-Finance report item.

### How

- If all cited clusters share one category, materialization continues to normalize the item to that category.
- If cited clusters span multiple categories, materialization narrows the item to one primary category and keeps only matching cluster/evidence lineage.
- The dropped clusters are left for quality gates and Reviewer/Editor loops to catch as missing selected-cluster coverage.

### Problems and Solutions

- Problem: A Writer draft created a generic `other` item named `Priority Follow-ups` while citing selected clusters from different report buckets.
  - Solution: Do not persist cross-category report items. Narrow the item to one verifiable category and let the writing loop repair omitted coverage.
- Problem: Strict category validation was correct, but too brittle at the raw Agent-output boundary.
  - Solution: Move the strictness one step later: materialize only a coherent item, then let gates enforce full report coverage.

## Part 27: Uncertain Research Language Repair

### Used

- Full-cycle smoke report and final Reviewer issues.
- Writing output materialization.
- Existing deterministic early-signal fact-language guard.

### Did

- Added deterministic hedging for `early_signal` and `research` report items.
- Preserved the Reviewer guard for explicit fact-language failures.
- Added regression coverage for overconfident uncertain-item key data and impact wording.

### How

- Materialization now prefixes uncertain key data with `Preprint claim (unvalidated)` unless already explicitly hedged.
- Research and early-signal potential impact is downgraded from `Medium to High` to `Low to Medium (preprint, unvalidated)`.
- Uncertain items receive peer-review / replication follow-up points when missing.
- Explicit fact markers like `confirmed`, `has launched`, and `has released` are not auto-repaired, so Reviewer can still block them.

### Problems and Solutions

- Problem: The full-cycle report covered all selected clusters, but final Reviewer repeatedly requested revisions because research preprint numbers were phrased too much like established facts.
  - Solution: Normalize common preprint/research language before report persistence, while keeping strict review for genuinely factual claims.
- Problem: A too-broad first repair pass masked explicit early-signal fact language in tests.
  - Solution: Add strong fact-marker detection so deterministic hedging does not hide claims that should fail review.

## Part 28: Non-Blocking Reviewer Finding Filter

### Used

- Full-cycle smoke review issues after the report reached complete selected-cluster coverage.
- Writing output materialization.
- Existing Reviewer and deterministic guard behavior.

### Did

- Added a deterministic filter for Reviewer findings that are already addressed in the report or allowed by Connor.ai's report contract.
- Added regression coverage for watchlist/body overlap being non-blocking.

### How

- Review materialization now filters issues such as allowed watchlist/body cluster overlap, already-caveated consensus-data absence, already-hedged preprint claims, official multi-update grouping, and generic follow-up specificity complaints when all items already have follow-ups.
- If all Reviewer findings are filtered and deterministic guards find no fact-language problem, the review is materialized as `pass`.
- Explicit early-signal fact claims still pass through the existing guard and remain blocking.
- Filter decisions are traced with `filtered_issue_count`.

### Problems and Solutions

- Problem: Full-cycle smoke reached a structurally complete report but exhausted writing rounds on Reviewer issues that were either already caveated or permitted by the product structure.
  - Solution: Separate blocking correctness issues from non-blocking product/editorial findings during materialization.
- Problem: Broadly weakening Reviewer would hide real quality failures.
  - Solution: Keep deterministic guard checks after filtering, so factual early-signal language still forces revision.

## Part 29: Reviewer Report ID Fallback

### Used

- Full-cycle smoke traceback.
- Writing review materialization.
- Daily report repository latest-report lookup.

### Did

- Hardened review materialization when Reviewer cites a malformed or stale `report_id`.
- Added regression coverage for fallback from a missing review `report_id`.

### How

- If a review draft includes a `report_id` that does not exist, materialization now falls back to the latest report for the current run.
- If no report exists for the run, the original error is still raised.
- Wrong-run report IDs remain rejected.

### Problems and Solutions

- Problem: A formal smoke run failed because Reviewer returned `report_...` while the actual persisted report ID was `report_..._main`.
  - Solution: Treat missing review report IDs as recoverable Agent-output drift and attach the review to the current run's latest report.

## Part 30: Review Filter and Trace Consistency Hardening

### Used

- Full-cycle smoke review issue dump.
- Report evidence map and trace timeline invariants.
- Writing materializer uncertainty repair.

### Did

- Strengthened deterministic hedging for uncertain/research core information.
- Expanded non-blocking review filtering for already-satisfied evidence, follow-up, and no-finance-day cases.
- Added an internal consistency check for evidence-map trace IDs before filtering Reviewer trace mismatch findings.

### How

- Research and early-signal core information now starts with `Preliminary signal, not independently validated:` unless it contains explicit fact markers that should remain review-blocking.
- Potential-impact repair now handles `Medium-to-high` variants.
- Reviewer findings about trace ID mismatch are filtered only when every evidence-map trace ID appears in the report trace timeline.
- Reviewer findings about absent Tech-Finance are filtered when the report has no Tech-Finance category to write.
- Reviewer findings about already-hedged arXiv/preprint evidence bundles and existing follow-up points are treated as non-blocking.

### Problems and Solutions

- Problem: Full-cycle smoke still exhausted revision rounds on review findings that were already satisfied in the latest report.
  - Solution: Make the filter check concrete report state instead of relying only on issue wording.
- Problem: Evidence-map trace mismatch might be a real structural bug.
  - Solution: Filter it only after verifying the report's evidence-map trace IDs are actually included in `trace_timeline_ids`.

## Part 31: Tech-Finance Impact Chain and Lineage Review Repair

### Used

- Full-cycle smoke report/review dump.
- Tech-Finance report materialization.
- Evidence-map and report-item lineage consistency checks.

### Did

- Strengthened Tech-Finance report item repair so tickers and impact chains are present even when the Writer already supplied partial impact text.
- Expanded non-blocking review filtering for evidence-map and evidence-ID complaints that are contradicted by actual report lineage.

### How

- Tech-Finance items now inherit tickers from cited clusters whenever the item omits them.
- Tech-Finance impact text now receives an explicit `Impact chain:` sentence when missing.
- Reviewer complaints about evidence maps, evidence mismatch, undeclared evidence, or missing evidence are filtered only when each report item has an evidence-map entry matching its item evidence and cluster IDs.
- Reviewer complaints about missing ticker metadata are filtered because `ReportItem` has ticker fields, not arbitrary metadata fields.

### Problems and Solutions

- Problem: Reviewer repeatedly blocked finalization on Tech-Finance items with partial but not explicit impact chains.
  - Solution: Make the materializer add the expected impact-chain structure deterministically.
- Problem: Reviewer sometimes reported stale evidence-map mismatches after the report lineage had already been repaired.
  - Solution: Validate the report's actual lineage before treating those review findings as blocking.

## Part 32: Report Item Follow-up and Text Normalization

### Used

- Full-cycle smoke Reviewer findings.
- Writing report item materialization.
- Reviewer non-blocking finding filter.

### Did

- Added deterministic default follow-up points for report items that arrive without any follow-up.
- Normalized report item text to remove emoji that can confuse renderers or model reviewers.
- Expanded review filtering for stale JSON/core-information, ticker metadata, overview contradiction, and formatting-only findings.

### How

- Report items now receive category-specific default follow-up points when Writer/Editor omits them.
- The materializer replaces the Hugging Face emoji with plain `Hugging Face` text.
- Reviewer claims about missing `core_information` are filtered only when the report JSON actually has non-empty `core_information` for every item.
- Ticker metadata complaints are filtered because `ReportItem` uses explicit ticker fields rather than arbitrary metadata.

### Problems and Solutions

- Problem: Reviewer blocked finalization on empty follow-up arrays and emoji/rendering concerns.
  - Solution: Normalize these at materialization time so final reports meet the dashboard/report contract.
- Problem: Reviewer reported missing JSON fields that were present in persisted `full_json`.
  - Solution: Check the actual `full_json` before allowing that finding to block the run.

## Part 33: Tomorrow Focus Derivation

### Used

- Full-cycle smoke final gate failure.
- Daily report materialization.
- Existing report section and watchlist structures.

### Did

- Added deterministic derivation for top-level `full_json.tomorrow_focus` when Writer only provides a Tomorrow Focus section or item follow-ups.
- Added regression coverage for deriving tomorrow focus from a dedicated section.

### How

- Materialization first uses explicit `draft.tomorrow_focus` when present.
- If missing, it collects follow-up points from sections whose ID/title indicates tomorrow focus.
- If no tomorrow section exists, it falls back to non-watchlist item follow-ups and then watchlist `next_watch` entries.
- The derived list is deduped and capped at five entries.

### Problems and Solutions

- Problem: Reviewer passed the report, but final gate paused because `full_json.tomorrow_focus` was empty even though the report contained a Tomorrow Focus section.
  - Solution: Treat top-level tomorrow focus as a structured artifact that can be derived from the normalized report body.

## Part 34: Deterministic Finalization After Non-Blocking Revisions

### Used

- Full-cycle smoke runs that reached structurally complete reports but remained paused on non-blocking Reviewer suggestions.
- Writing quality gate.
- Review issue priorities.

### Did

- Added a deterministic finalization path when revision budget is exhausted but final report hard requirements pass.
- Added regression coverage for this gate behavior.

### How

- If the latest review is `revise` and revision budget is exhausted, the gate checks final report requirements.
- If no final requirements are missing and the latest review has no P0/P1 blocking issues, the gate returns `FINALIZE`.
- The decision carries `finalized_with_non_blocking_review_findings` as a risk flag and records a metric.

### Problems and Solutions

- Problem: LLM Reviewer can keep producing useful but non-blocking editorial suggestions indefinitely, causing formal runs to pause despite a complete report.
  - Solution: Let deterministic harness gates decide when hard requirements are satisfied after the revision budget is spent.
- Problem: Blindly finalizing after budget could hide serious issues.
  - Solution: Require all final report checks to pass and block if the latest review still contains P0/P1 issues.

## Part 35: Evaluator Missing Cluster Guard

### Used

- Full-cycle smoke traceback from Evaluator materialization.
- Evaluator output materializer.
- Trace service.

### Did

- Hardened Evaluator materialization when an Evaluator draft references a missing or wrong-run cluster ID.
- Added regression coverage for missing cluster IDs.

### How

- Evaluator drafts now resolve clusters with `get()` rather than hard `require()`.
- Missing or wrong-run clusters are skipped with a trace event and `skip_reason=missing_or_wrong_run_cluster`.
- Valid drafts still materialize normally and category-ineligible drafts still use the existing skip path.

### Problems and Solutions

- Problem: A formal smoke run failed because an Evaluator cited a cluster ID that did not exist in the run.
  - Solution: Treat invalid evaluator cluster references as recoverable Agent-output drift; skip and trace instead of failing the run.

## Part 36: Deterministic Report Shape and Final Smoke

### Used

- Final full-cycle smoke report from `test_tmp/phase15a_full_cycle.db`.
- Writer output materializer.
- Reviewer materializer and final writing gate.
- Report markdown / JSON / evidence map records.

### Did

- Inspected the generated report as a business artifact, not only as a passing test artifact.
- Found and fixed duplicate Watchlist rendering in Markdown.
- Normalized report sections into Connor.ai's canonical order: Early Signals, Confirmed Events, Tech-Finance, Watchlist.
- Stopped trusting model-provided `full_markdown` as the final artifact when structured report sections are available.
- Removed redundant early-signal caveat prefixes from `core_information` while preserving uncertainty labels, key-data hedging, and deterministic fact-language guards.
- Treated redundant uncertainty-prefix and generic follow-up Reviewer remarks as non-blocking when the structured report already satisfies final requirements.

### How

- Added deterministic section normalization in `WritingOutputMaterializer`.
- Re-rendered final Markdown from structured sections, `watchlist_updates`, and `tomorrow_focus`.
- Rendered Watchlist exactly once: section items take precedence; otherwise structured `watchlist_updates` are rendered.
- Added regression tests for canonical section ordering, deterministic Markdown, Watchlist de-duplication, and redundant uncertainty-prefix review filtering.

### Problems and Solutions

- Problem: A finalized report could show both a model-written Watchlist section and a system-appended Watchlist section.
  - Solution: Make the materializer the single renderer for final Markdown and render Watchlist through one deterministic path.
- Problem: Reviewer repeatedly asked to remove a redundant `Preliminary signal, not independently validated:` prefix from early-signal body text.
  - Solution: Keep uncertainty in status, labels, impact, and key data, but avoid duplicating the same caveat in `core_information`.
- Problem: A strict smoke retry paused after three writing rounds due to copy-edit level comments.
  - Solution: Filter non-blocking review text after deterministic report checks and rerun the strict smoke to completion.

## Current Checks

- `python -m ruff check app\agents\runner.py app\agents\registry.py tests\agents\test_runner.py tests\agents\test_registry.py`: passed.
- `python -m pytest tests\agents\test_runner.py tests\agents\test_registry.py -q`: 17 passed.
- Targeted live Social Scout smoke: completed in 22.66 seconds with 1 tool result and 1 candidate draft.
- `python -m ruff check app\clusterer\materialization.py tests\clusterer\test_materialization.py`: passed.
- `python -m pytest tests\clusterer\test_materialization.py -q`: 6 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 12 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 84 passed.
- `python -m pytest -q --ignore=tests\smoke`: 167 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 13 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 85 passed.
- `python -m pytest -q --ignore=tests\smoke`: 168 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 14 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 86 passed.
- `python -m pytest -q --ignore=tests\smoke`: 169 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 15 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 87 passed.
- `python -m pytest -q --ignore=tests\smoke`: 170 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 15 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 87 passed.
- `python -m pytest -q --ignore=tests\smoke`: 170 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 15 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 87 passed.
- `python -m pytest -q --ignore=tests\smoke`: 170 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 16 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 88 passed.
- `python -m pytest -q --ignore=tests\smoke`: 171 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 17 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 89 passed.
- `python -m pytest -q --ignore=tests\smoke`: 172 passed.
- `python -m ruff check app\harness\gates.py tests\harness\test_quality_gates.py`: passed.
- `python -m pytest tests\harness\test_quality_gates.py -q`: 9 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 90 passed.
- `python -m pytest -q --ignore=tests\smoke`: 173 passed.
- `python -m ruff check app\evaluators\materialization.py tests\evaluators\test_materialization.py`: passed.
- `python -m pytest tests\evaluators\test_materialization.py -q`: 7 passed.
- `python -m pytest tests\agents tests\clusterer tests\evaluators tests\harness tests\scouts tests\writing tests\watchlist -q`: 103 passed.
- `python -m pytest -q --ignore=tests\smoke`: 174 passed.
- `python -m pytest tests\harness\test_quality_gates.py tests\writing\test_tasks.py -q`: 9 passed.
- `python -m pytest tests\harness tests\writing -q`: 35 passed.
- `python -m pytest tests\agents\test_runner.py tests\evaluators\test_materialization.py tests\tools\test_source_tools.py -q`: 45 passed.
- `python -m pytest -q --ignore=tests\smoke`: 146 passed.
- `python -m pytest tests\agents\test_runner.py tests\writing tests\harness\test_quality_gates.py -q`: 28 passed.
- `python -m pytest tests\harness\test_writing_loop.py -q`: 2 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py -q`: 48 passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 7 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py -q`: 49 passed.
- `python -m pytest -q --ignore=tests\smoke`: 149 passed.
- `python -m pytest tests\writing\test_materialization.py tests\harness\test_quality_gates.py -q`: 16 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py -q`: 51 passed.
- `python -m pytest -q --ignore=tests\smoke`: 151 passed.
- `python -m pytest tests\agents\test_runner.py::test_agent_runner_uses_writer_fallback_after_failed_repair tests\agents\test_runner.py::test_agent_runner_uses_clusterer_fallback_after_failed_repair -q`: 2 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py -q`: 52 passed.
- `python -m pytest -q --ignore=tests\smoke`: 152 passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 9 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py -q`: 53 passed.
- `python -m pytest -q --ignore=tests\smoke`: 153 passed.
- `python -m pytest tests\watchlist\test_materialization.py -q`: 5 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py tests\watchlist -q`: 62 passed.
- `python -m pytest -q --ignore=tests\smoke`: 154 passed.
- `python -m pytest tests\writing\test_tasks.py -q`: 3 passed.
- `python -m pytest -q --ignore=tests\smoke`: 154 passed.
- `python -m pytest tests\agents\test_runner.py::test_agent_runner_normalizes_actionable_reviewer_reject_to_revise tests\agents\test_runner.py::test_agent_runner_normalizes_reviewer_pass_with_issues -q`: 2 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py tests\watchlist -q`: 63 passed.
- `python -m pytest -q --ignore=tests\smoke`: 155 passed.
- `python -m ruff check app\harness\materialization.py tests\harness\test_all_scouts_closed_loop.py`: passed.
- `python -m pytest tests\harness\test_all_scouts_closed_loop.py -q`: 9 passed.
- `python -m pytest tests\harness tests\writing tests\agents\test_runner.py tests\watchlist -q`: 64 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 156 passed.
- `python -m ruff check app\config.py app\agents\registry.py app\harness\config.py app\harness\collect.py tests\agents\test_registry.py tests\harness\test_collect_loop.py`: passed.
- `python -m pytest tests\agents\test_registry.py tests\harness\test_collect_loop.py -q`: 6 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 68 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 158 passed.
- `python -m ruff check app\agents\model_factory.py tests\agents\test_model_factory.py app\agents\registry.py app\harness\collect.py tests\agents\test_registry.py tests\harness\test_collect_loop.py`: passed.
- `python -m pytest tests\agents\test_model_factory.py tests\agents\test_registry.py tests\harness\test_collect_loop.py -q`: 7 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 69 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 159 passed.
- `python -m ruff check app\agents\model_factory.py tests\agents\test_model_factory.py`: passed.
- `python -m pytest tests\agents\test_model_factory.py tests\smoke\test_deepseek_integration.py::test_deepseek_model_responds_to_prompt -q`: 2 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 69 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 159 passed.
- `python -m ruff check app\harness\materialization.py tests\harness\test_all_scouts_closed_loop.py`: passed.
- `python -m pytest tests\harness\test_all_scouts_closed_loop.py -q`: 10 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 70 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 160 passed.
- `python -m ruff check app\agents\runner.py tests\agents\test_runner.py`: passed.
- `python -m pytest tests\agents\test_runner.py -q`: 15 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 71 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 161 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 11 passed.
- `python -m pytest tests\agents tests\harness tests\writing tests\watchlist -q`: 73 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 163 passed.
- `python -m ruff check app\clusterer\materialization.py tests\clusterer\test_materialization.py`: passed.
- `python -m pytest tests\clusterer\test_materialization.py -q`: 5 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\writing tests\watchlist -q`: 78 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 165 passed.
- Strict smoke retry 17: terminated after extended runtime with no new phase output; no final pass yet.
- `python -m ruff check app\agents\registry.py app\harness\collect.py app\harness\writing.py app\scouts\tasks.py tests\agents\test_registry.py tests\harness\test_collect_loop.py tests\harness\test_writing_loop.py`: passed.
- `python -m pytest tests\agents\test_registry.py tests\harness\test_collect_loop.py tests\harness\test_writing_loop.py -q`: 8 passed.
- `python -m pytest tests\agents tests\clusterer tests\harness tests\scouts tests\writing tests\watchlist -q`: 82 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 165 passed.
- `python -m ruff check app\writing\materialization.py tests\writing\test_materialization.py`: passed.
- `python -m pytest tests\writing\test_materialization.py -q`: 20 passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --ignore=tests\smoke`: 177 passed.
- Strict live full-cycle smoke: 1 passed in 371.32 seconds.
  - Final run: `finalized / completed`.
  - Report status: `final`.
  - Sections: Early Signals, Confirmed Events, Tech-Finance.
  - Watchlist: rendered once from structured updates.
  - Evidence map entries: 3.
  - Markdown length: 7369 characters.

## Remaining

- Phase 15A formal-run hardening is complete.
- Phase 15B should improve business substance: evidence URL deduplication, source diversity, evaluator/write-policy calibration, SEC filing content extraction, and finance-number extraction.
- Remaining runtime warnings to clean up later: unknown `pytest.mark.slow` registration and expected AgentScope max-iteration warnings from bounded Scout ReAct loops.
