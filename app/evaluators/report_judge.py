"""LLM-as-Judge report quality evaluator.

After the writing loop finalizes a DailyReport, an independent judge
model call scores the report on seven dimensions.  Scores are persisted
as ``ReportEvaluation`` records and can be used to track quality trends
over time without manual review.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.agents.outputs import AgentStructuredOutput
from app.core.ids import IdPrefix, random_id
from app.domain import (
    AgentRole,
    DailyReport,
    ReportEvaluation,
    RunPhase,
    TraceEventType,
    TraceStatus,
)
from app.domain.base import utc_now
from app.repositories.runs import FullRunState
from app.services import TraceService

JUDGE_SYSTEM_PROMPT = """\
You are a quality judge for daily AI-intelligence reports written in Chinese.
Your job is to read a full report and assign 0-10 scores on seven dimensions,
with a one-line reason for each score in English.

## Scoring dimensions

1. **accuracy** — Are preprints/unconfirmed signals clearly marked as such?
   No confirmed-fact language on early signals? 10 = perfect hedging, 0 = preprint
   presented as product launch.

2. **completeness** — Does the report cover every selected cluster?  Are the
   five standard sections populated (early_signals, confirmed_events,
   tech_finance, watchlist, tomorrow_focus)?

3. **prudence** — Are early-signal items hedged with uncertainty markers
   ("preprint / unconfirmed", "pending peer review", etc.)?  10 = every early
   signal has clear uncertainty language, 0 = none do.

4. **structure** — Are sections logically ordered?  Are body/watchlist item
   counts correct?  Is the overview consistent with the body?

5. **readability** — Is the Simplified Chinese natural and fluent?  Any
   English boilerplate, enum values, or template text leaking through?
   10 = native-level Chinese, 0 = machine-translated garbage.

6. **actionability** — Are followup points specific and date-anchored?
   Does tomorrow_focus reference concrete catalysts?  10 = every followup
   is specific and dated, 0 = all generic "monitor for updates".

7. **finance_quality** — If the Tech-Finance section has body items: are
   data points cited?  Are tickers valid?  Are impact chains supported?
   If the section is empty, score N/A (null).  10 = rigorous finance
   analysis, 0 = fabricated numbers or pseudo-tickers.

## Output format

Return a single JSON object (no markdown fences, no extra text):

{
  "accuracy": <0-10>,
  "accuracy_reason": "<one line>",
  "completeness": <0-10>,
  "completeness_reason": "<one line>",
  "prudence": <0-10>,
  "prudence_reason": "<one line>",
  "structure": <0-10>,
  "structure_reason": "<one line>",
  "readability": <0-10>,
  "readability_reason": "<one line>",
  "actionability": <0-10>,
  "actionability_reason": "<one line>",
  "finance_quality": <0-10 or null>,
  "finance_quality_reason": "<one line>",
  "critical_issues": ["<issue>" or empty list],
  "suggestions": ["<suggestion>" or empty list],
  "overall_reasoning": "<2-4 sentence synthesis>"
}
"""


class ReportJudge:
    """Evaluate a finalized DailyReport with an independent LLM call."""

    def __init__(
        self,
        session: Any,
        *,
        trace_service: TraceService | None = None,
    ):
        self._session = session
        self._trace_service = trace_service
        self._judge_model_name = "deepseek-chat"

    def evaluate(
        self,
        report: DailyReport,
        full_state: FullRunState,
        *,
        model_factory: Any | None = None,
        agent_timeout_seconds: int = 120,
    ) -> ReportEvaluation | None:
        """Run the judge and return a ReportEvaluation, or None on failure."""

        if model_factory is None:
            return None

        run_id = report.run_id
        report_id = report.id
        started_at = time.monotonic()

        # ---- build judge context ----
        report_text = self._build_report_context(report)
        if not report_text.strip():
            return None

        # ---- call the judge model ----
        try:
            judge_output = self._call_judge(
                report_text=report_text,
                model_factory=model_factory,
                timeout_seconds=agent_timeout_seconds,
            )
        except Exception as exc:
            if self._trace_service:
                try:
                    self._trace_service.record_event(
                        run_id=run_id,
                        phase=RunPhase.FINALIZED,
                        agent_role=AgentRole.REVIEWER,
                        event_type=TraceEventType.ERROR,
                        status=TraceStatus.FAILED,
                        summary="Report judge model call failed.",
                        error=str(exc) or type(exc).__name__,
                        metadata={"report_id": report_id},
                    )
                except Exception:
                    pass
            return None

        duration_ms = int((time.monotonic() - started_at) * 1000)

        # ---- build evaluation ----
        total = self._compute_total(judge_output)
        evaluation = ReportEvaluation(
            id=random_id(IdPrefix.EVAL, parts=[report_id], length=16),
            report_id=report_id,
            run_id=run_id,
            evaluated_at=utc_now(),
            accuracy=judge_output.get("accuracy", 0),
            completeness=judge_output.get("completeness", 0),
            prudence=judge_output.get("prudence", 0),
            structure=judge_output.get("structure", 0),
            readability=judge_output.get("readability", 0),
            actionability=judge_output.get("actionability", 0),
            finance_quality=judge_output.get("finance_quality"),
            total_score=round(total, 2),
            critical_issues=judge_output.get("critical_issues") or [],
            suggestions=judge_output.get("suggestions") or [],
            reasoning=judge_output.get("overall_reasoning", ""),
            judge_model=self._judge_model_name,
            judge_duration_ms=duration_ms,
        )

        # ---- persist ----
        from app.db.models.report_evaluation import ReportEvaluationRecord

        record = ReportEvaluationRecord(
            id=evaluation.id,
            report_id=evaluation.report_id,
            run_id=evaluation.run_id,
            payload=evaluation.model_dump(mode="json"),
            created_at=evaluation.evaluated_at,
        )
        self._session.add(record)
        self._session.flush()

        # ---- trace ----
        if self._trace_service:
            self._trace_service.record_event(
                run_id=run_id,
                phase=RunPhase.FINALIZED,
                agent_role=AgentRole.REVIEWER,
                event_type=TraceEventType.REVIEW_COMPLETED,
                status=TraceStatus.SUCCEEDED,
                summary=f"Report judge scored {total:.1f}/10 on {len(evaluation.suggestions)} suggestions.",
                output_payload=evaluation.model_dump(mode="json"),
                metadata={
                    "judge": True,
                    "report_id": report_id,
                    "total_score": total,
                    "duration_ms": duration_ms,
                },
            )

        return evaluation

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report_context(report: DailyReport) -> str:
        """Build a compact text block for the judge to evaluate."""
        parts: list[str] = []

        if report.full_markdown:
            # Truncate to keep judge prompt within reasonable token budget
            markdown = report.full_markdown
            if len(markdown) > 12000:
                markdown = markdown[:12000] + "\n\n... [report truncated for judge]"
            parts.append(markdown)
            return "\n\n".join(parts)

        # Fallback: build from sections if no rendered markdown
        parts.append(f"# {report.title}")
        parts.append(f"Date: {report.report_date.isoformat()}")
        if report.overview_judgments:
            parts.append("## Overview\n" + "\n".join(report.overview_judgments))
        for section in report.sections:
            parts.append(f"## {section.title}")
            for item in section.items:
                parts.append(f"### {item.title}")
                parts.append(f"Status: {item.status_label}")
                parts.append(f"Core: {item.core_information}")
                if item.why_it_matters:
                    parts.append(f"Why: {item.why_it_matters}")
                if item.potential_impact:
                    parts.append(f"Impact: {item.potential_impact}")
                if item.tickers:
                    parts.append(f"Tickers: {', '.join(item.tickers)}")
                if item.followup_points:
                    parts.append(f"Followup: {'; '.join(item.followup_points)}")
        if report.tomorrow_focus:
            parts.append("## Tomorrow Focus\n" + "\n".join(report.tomorrow_focus))
        return "\n\n".join(parts)

    def _call_judge(
        self,
        *,
        report_text: str,
        model_factory: Any,
        timeout_seconds: int,
    ) -> dict:
        """Call the DeepSeek judge model and parse its JSON response."""

        import asyncio

        from app.agents.config import AgentExecutionConfig, AgentRoleConfig

        # Minimal role config for a no-tools judge call
        config = AgentRoleConfig(
            role=AgentRole.REVIEWER,
            display_name="Report Judge",
            system_prompt=JUDGE_SYSTEM_PROMPT,
            allowed_tool_names=[],
            output_model=AgentStructuredOutput,
            execution=AgentExecutionConfig(
                max_iters=1,
                max_tool_calls=0,
                timeout_seconds=timeout_seconds,
                model_name=self._judge_model_name,
            ),
        )

        model = model_factory(config)

        async def _judge() -> dict:
            from agentscope.agent import Agent
            from agentscope.message import UserMsg

            agent = Agent(
                name="ReportJudge",
                system_prompt=JUDGE_SYSTEM_PROMPT,
                model=model,
                toolkit=None,
            )
            user_msg = UserMsg(
                name="judge_harness",
                content=json.dumps(
                    {
                        "task": "Score the following Connor.ai daily intelligence report.",
                        "report": report_text,
                        "output_rule": (
                            "Return ONLY a single JSON object. No markdown fences, "
                            "no extra text before or after the JSON."
                        ),
                    },
                    ensure_ascii=False,
                ),
                role="user",
            )
            response = await agent.reply(user_msg)
            text = response.get_text_content()
            if text is None:
                raise RuntimeError("Judge returned empty response")

            return self._parse_judge_json(text)

        try:
            return asyncio.run(_judge())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_judge())
            finally:
                loop.close()

    @staticmethod
    def _parse_judge_json(text: str) -> dict:
        """Extract JSON object from judge response, tolerating markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        # Find first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in judge response: " + text[:200])
        return json.loads(text[start : end + 1])  # type: ignore[no-any-return]

    @staticmethod
    def _compute_total(scores: dict) -> float:
        """Weighted average of the seven dimensions."""
        dims = [
            ("accuracy", 0.20),
            ("completeness", 0.15),
            ("prudence", 0.20),
            ("structure", 0.10),
            ("readability", 0.15),
            ("actionability", 0.10),
        ]
        total = 0.0
        weight_sum = 0.0
        for key, weight in dims:
            val = scores.get(key, 0)
            if val is None:
                continue
            total += float(val) * weight
            weight_sum += weight
        # finance_quality is optional
        fq = scores.get("finance_quality")
        if fq is not None:
            total += float(fq) * 0.10
            weight_sum += 0.10
        if weight_sum == 0:
            return 0.0
        return total / weight_sum
