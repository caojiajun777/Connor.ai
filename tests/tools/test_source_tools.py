"""Real source tool normalization tests."""

from dataclasses import dataclass

from app.domain import AgentRole, RunPhase, SourceType, ToolCallStatus
from app.repositories import EvidenceRepository, RunRepository
from app.services import TraceService
from app.tools import (
    ToolExecutionContext,
    ToolExecutor,
    api_changelog_search_tool,
    arxiv_search_tool,
    create_default_tool_registry,
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
from app.tools.http import JsonHttpResponse, SourceHttpError, TextHttpResponse
from tests.domain.fixtures import RUN_ID, run_state_fixture


@dataclass
class FakeJsonClient:
    payload: object
    text: str | None = None
    payloads: list[object] | None = None
    texts: list[str] | None = None
    headers: dict[str, str] | None = None
    status_code: int = 200
    error: SourceHttpError | None = None
    calls: list[dict] | None = None

    def get_json(self, url, *, query_params=None, headers=None, timeout_seconds=20):
        if self.calls is None:
            self.calls = []
        self.calls.append(
            {
                "url": url,
                "query_params": query_params,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        payload = self.payloads.pop(0) if self.payloads else self.payload
        return JsonHttpResponse(
            payload=payload,
            status_code=self.status_code,
            headers=self.headers or {},
            url=url,
        )

    def get_text(self, url, *, query_params=None, headers=None, timeout_seconds=20):
        if self.calls is None:
            self.calls = []
        self.calls.append(
            {
                "url": url,
                "query_params": query_params,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        text = self.texts.pop(0) if self.texts else self.text or ""
        return TextHttpResponse(
            text=text,
            status_code=self.status_code,
            headers=self.headers or {},
            url=url,
        )


def test_github_repository_search_normalizes_repositories() -> None:
    client = FakeJsonClient(
        payload={
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "id": 42,
                    "full_name": "openai/example-agents",
                    "html_url": "https://github.com/openai/example-agents",
                    "description": "Agent examples for a new API surface.",
                    "updated_at": "2026-07-03T12:00:00Z",
                    "stargazers_count": 100,
                    "forks_count": 10,
                    "language": "Python",
                    "topics": ["agents", "reasoning"],
                    "owner": {"login": "openai"},
                    "license": {"spdx_id": "MIT"},
                }
            ],
        },
        headers={"x-ratelimit-remaining": "59"},
    )

    envelope = github_repository_search_tool(_context("reasoning agents"), client=client)

    assert envelope.tool_name == "github_repository_search"
    assert envelope.source_type == SourceType.GITHUB
    assert envelope.items[0].title == "openai/example-agents"
    assert envelope.items[0].author == "openai"
    assert envelope.items[0].metadata["stars"] == 100
    assert envelope.rate_limit["x-ratelimit-remaining"] == "59"
    assert client.calls[0]["query_params"]["per_page"] == 10


def test_github_code_search_normalizes_file_hits() -> None:
    client = FakeJsonClient(
        payload={
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "name": "api.py",
                    "path": "src/api.py",
                    "sha": "abc123",
                    "html_url": "https://github.com/acme/sdk/blob/main/src/api.py",
                    "repository": {
                        "full_name": "acme/sdk",
                        "owner": {"login": "acme"},
                    },
                }
            ],
        }
    )

    envelope = github_code_search_tool(_context("reasoning_effort"), client=client)

    assert envelope.items[0].title == "acme/sdk:src/api.py"
    assert envelope.items[0].raw_ref == "abc123"
    assert envelope.items[0].metadata["repository"] == "acme/sdk"


def test_huggingface_model_and_dataset_search_normalize_results() -> None:
    model_client = FakeJsonClient(
        payload=[
            {
                "modelId": "qwen/qwen-test",
                "pipeline_tag": "text-generation",
                "library_name": "transformers",
                "tags": ["llm", "reasoning"],
                "downloads": 1234,
                "likes": 50,
                "lastModified": "2026-07-03T11:00:00.000Z",
            }
        ]
    )
    dataset_client = FakeJsonClient(
        payload=[
            {
                "id": "bench/reasoning-eval",
                "tags": ["benchmark"],
                "downloads": 100,
                "likes": 5,
                "lastModified": "2026-07-03T10:00:00.000Z",
            }
        ]
    )

    model_envelope = huggingface_model_search_tool(_context("qwen reasoning"), client=model_client)
    dataset_envelope = huggingface_dataset_search_tool(_context("reasoning benchmark"), client=dataset_client)

    assert model_envelope.items[0].url == "https://huggingface.co/qwen/qwen-test"
    assert model_envelope.items[0].metadata["pipeline_tag"] == "text-generation"
    assert dataset_envelope.items[0].url == "https://huggingface.co/datasets/bench/reasoning-eval"
    assert dataset_envelope.items[0].metadata["kind"] == "dataset"


def test_arxiv_search_normalizes_atom_feed() -> None:
    client = FakeJsonClient(
        payload=None,
        text="""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>1</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2601.00001v1</id>
    <title> Reasoning Agents for Scientific Discovery </title>
    <updated>2026-01-02T00:00:00Z</updated>
    <published>2026-01-01T00:00:00Z</published>
    <summary> We study agentic reasoning systems. </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Grace Hopper</name></author>
    <category term="cs.AI" />
    <arxiv:primary_category term="cs.AI"/>
    <link href="https://arxiv.org/pdf/2601.00001v1" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>""",
    )

    envelope = arxiv_search_tool(_context("reasoning agents"), client=client)

    assert envelope.tool_name == "arxiv_search"
    assert envelope.source_type == SourceType.ARXIV
    assert envelope.items[0].title == "Reasoning Agents for Scientific Discovery"
    assert envelope.items[0].author == "Ada Lovelace, Grace Hopper"
    assert envelope.items[0].metadata["arxiv_id"] == "2601.00001v1"
    assert envelope.items[0].metadata["primary_category"] == "cs.AI"
    assert client.calls[0]["query_params"]["search_query"] == "all:reasoning agents"


def test_openreview_note_search_normalizes_notes() -> None:
    client = FakeJsonClient(
        payload={
            "count": 1,
            "notes": [
                {
                    "id": "note123",
                    "forum": "forum123",
                    "replyto": None,
                    "invitation": "ICLR.cc/2026/Conference/-/Submission",
                    "number": 7,
                    "cdate": 1767225600000,
                    "tmdate": 1767312000000,
                    "content": {
                        "title": {"value": "Test-Time Reasoning for Agents"},
                        "abstract": {"value": "A benchmark for reasoning agents."},
                        "authors": {"value": ["Ada Lovelace"]},
                        "venue": {"value": "ICLR 2026"},
                    },
                }
            ],
        }
    )

    envelope = openreview_note_search_tool(_context("reasoning agents"), client=client)

    assert envelope.tool_name == "openreview_note_search"
    assert envelope.source_type == SourceType.OPENREVIEW
    assert envelope.items[0].title == "Test-Time Reasoning for Agents"
    assert envelope.items[0].url == "https://openreview.net/forum?id=note123"
    assert envelope.items[0].metadata["venue"] == "ICLR 2026"
    assert client.calls[0]["query_params"]["content.title"] == "reasoning agents"


def test_official_feed_search_normalizes_rss_entries() -> None:
    client = FakeJsonClient(
        payload=None,
        text="""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>OpenAI News</title>
    <item>
      <title>New reasoning model update</title>
      <link>https://openai.com/news/reasoning-update</link>
      <guid>openai-reasoning-update</guid>
      <dc:creator>OpenAI</dc:creator>
      <pubDate>Fri, 03 Jul 2026 12:00:00 GMT</pubDate>
      <description><![CDATA[<p>Official launch notes for a reasoning model.</p>]]></description>
    </item>
  </channel>
</rss>""",
    )

    envelope = official_feed_search_tool(
        _context("reasoning", params={"source_keys": ["openai_news"]}),
        client=client,
    )

    assert envelope.tool_name == "official_feed_search"
    assert envelope.source_type == SourceType.OFFICIAL_BLOG
    assert envelope.items[0].title == "New reasoning model update"
    assert envelope.items[0].snippet == "Official launch notes for a reasoning model."
    assert envelope.items[0].metadata["source_key"] == "openai_news"
    assert envelope.items[0].metadata["feed_format"] == "rss"
    assert client.calls[0]["url"] == "https://openai.com/news/rss.xml"


def test_api_changelog_search_normalizes_html_sections() -> None:
    client = FakeJsonClient(
        payload=None,
        text="""<!doctype html>
<html>
  <head><title>OpenAI API Changelog</title></head>
  <body>
    <nav>
      <h2>Responses API fake navigation</h2>
      <p>Reasoning docs link from site navigation.</p>
    </nav>
    <h2>Suggested</h2>
    <p>Reasoning docs link from site navigation.</p>
    <main>
      <h2>Responses API reasoning controls</h2>
      <p>Official changelog confirms a new reasoning effort parameter.</p>
      <h2>Audio update</h2>
      <p>Speech model release notes.</p>
    </main>
  </body>
</html>""",
    )

    envelope = api_changelog_search_tool(
        _context("reasoning", params={"source_key": "openai_api_changelog"}),
        client=client,
    )

    assert envelope.tool_name == "api_changelog_search"
    assert envelope.source_type == SourceType.API_CHANGELOG
    assert len(envelope.items) == 1
    assert envelope.items[0].title == "OpenAI API Changelog: Responses API reasoning controls"
    assert envelope.items[0].metadata["kind"] == "official_changelog_page_section"
    assert envelope.items[0].metadata["source_key"] == "openai_api_changelog"


def test_official_source_unknown_key_returns_structured_error_without_request() -> None:
    client = FakeJsonClient(payload=None, text="")

    envelope = official_feed_search_tool(
        _context("reasoning", params={"source_keys": ["not_a_source"]}),
        client=client,
    )

    assert envelope.items == []
    assert envelope.errors[0].code == "unknown_source_key"
    assert envelope.metadata["unknown_source_keys"] == ["not_a_source"]
    assert client.calls is None


def test_official_feed_malformed_xml_returns_structured_error() -> None:
    client = FakeJsonClient(payload=None, text="<rss")

    envelope = official_feed_search_tool(
        _context("reasoning", params={"source_key": "openai_news"}),
        client=client,
    )

    assert envelope.items == []
    assert envelope.errors[0].code == "openai_news_unexpected_payload"
    assert envelope.metadata["source_results"][0]["status"] == "unexpected_payload"


def test_sec_company_filings_resolves_ticker_and_normalizes_filings() -> None:
    client = FakeJsonClient(
        payload=None,
        payloads=[
            {
                "0": {
                    "cik_str": 1045810,
                    "ticker": "NVDA",
                    "title": "NVIDIA CORP",
                }
            },
            {
                "cik": "0001045810",
                "name": "NVIDIA CORP",
                "tickers": ["NVDA"],
                "filings": {
                    "recent": {
                        "accessionNumber": ["0001045810-26-000123", "0001045810-26-000111"],
                        "filingDate": ["2026-05-20", "2026-03-01"],
                        "reportDate": ["2026-04-30", "2026-02-28"],
                        "acceptanceDateTime": ["2026-05-20T16:20:00.000Z", "2026-03-01T12:00:00.000Z"],
                        "form": ["10-Q", "8-K"],
                        "primaryDocument": ["nvda-20260430.htm", "nvda-8k.htm"],
                        "primaryDocDescription": ["FORM 10-Q", "FORM 8-K"],
                        "isXBRL": [1, 0],
                        "isInlineXBRL": [1, 0],
                        "size": [123456, 45678],
                    }
                },
            },
        ],
    )

    envelope = sec_company_filings_tool(
        _context("NVDA AI revenue", params={"ticker": "NVDA", "forms": ["10-Q"], "max_results": 5}),
        client=client,
    )

    assert envelope.tool_name == "sec_company_filings"
    assert envelope.source_type == SourceType.SEC_FILING
    assert len(envelope.items) == 1
    assert envelope.items[0].title == "NVDA 10-Q filed 2026-05-20"
    assert envelope.items[0].metadata["cik"] == "0001045810"
    assert envelope.items[0].metadata["accession_number"] == "0001045810-26-000123"
    assert envelope.items[0].url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-20260430.htm"
    )
    assert client.calls[0]["url"] == "https://www.sec.gov/files/company_tickers.json"
    assert client.calls[1]["url"] == "https://data.sec.gov/submissions/CIK0001045810.json"


def test_sec_company_facts_normalizes_xbrl_facts() -> None:
    client = FakeJsonClient(
        payload=None,
        payloads=[
            {
                "0": {
                    "cik_str": 1045810,
                    "ticker": "NVDA",
                    "title": "NVIDIA CORP",
                }
            },
            {
                "cik": 1045810,
                "entityName": "NVIDIA CORP",
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "label": "Revenues",
                            "description": "Revenue from contracts with customers.",
                            "units": {
                                "USD": [
                                    {
                                        "val": 44062000000,
                                        "fy": 2026,
                                        "fp": "Q1",
                                        "form": "10-Q",
                                        "filed": "2026-05-20",
                                        "end": "2026-04-30",
                                        "accn": "0001045810-26-000123",
                                        "frame": "CY2026Q1",
                                    }
                                ]
                            },
                        }
                    }
                },
            },
        ],
    )

    envelope = sec_company_facts_tool(
        _context("NVDA revenues", params={"ticker": "NVDA", "concepts": ["Revenues"], "max_results": 1}),
        client=client,
    )

    assert envelope.tool_name == "sec_company_facts"
    assert envelope.source_type == SourceType.SEC_FILING
    assert envelope.items[0].title == "NVDA Revenues 2026 Q1"
    assert "44062000000 USD" in envelope.items[0].snippet
    assert envelope.items[0].metadata["concept"] == "Revenues"
    assert envelope.items[0].metadata["value"] == 44062000000
    assert envelope.items[0].url == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123"


def test_sec_company_tool_requires_identifier() -> None:
    client = FakeJsonClient(payload=None)

    envelope = sec_company_filings_tool(_context("nvidia revenue"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "missing_company_identifier"
    assert client.calls is None


def test_investor_relations_search_normalizes_curated_pages() -> None:
    client = FakeJsonClient(
        payload=None,
        text="""<!doctype html>
<html>
  <head><title>NVIDIA Financial Reports</title></head>
  <body>
    <main>
      <h2>Quarterly Results</h2>
      <p>Data center revenue and AI infrastructure demand increased in the quarter.</p>
      <h2>Corporate Governance</h2>
      <p>Board committee information.</p>
    </main>
  </body>
</html>""",
    )

    envelope = investor_relations_search_tool(
        _context("AI revenue", params={"source_key": "nvidia_financial_reports"}),
        client=client,
    )

    assert envelope.tool_name == "investor_relations_search"
    assert envelope.source_type == SourceType.INVESTOR_RELATIONS
    assert len(envelope.items) == 1
    assert envelope.items[0].title == "NVIDIA Investor Relations Financial Reports: Quarterly Results"
    assert envelope.items[0].metadata["kind"] == "investor_relations_page_section"
    assert envelope.items[0].metadata["source_key"] == "nvidia_financial_reports"


def test_hacker_news_feed_search_normalizes_matching_items() -> None:
    client = FakeJsonClient(
        payload=None,
        payloads=[
            [101, 102, 103],
            {
                "id": 101,
                "type": "story",
                "by": "pg",
                "time": 1767225600,
                "title": "OpenAI releases a new reasoning API",
                "url": "https://openai.com/news/reasoning-api",
                "score": 500,
                "descendants": 123,
                "kids": [201, 202],
            },
            {
                "id": 102,
                "type": "story",
                "by": "someone",
                "time": 1767225601,
                "title": "Unrelated database release",
                "url": "https://example.com/db",
                "score": 10,
                "descendants": 3,
            },
        ],
    )

    envelope = hacker_news_feed_search_tool(
        _context("reasoning api", params={"feed": "new", "fetch_limit": 2, "max_results": 1}),
        client=client,
    )

    assert envelope.tool_name == "hacker_news_feed_search"
    assert envelope.source_type == SourceType.HACKER_NEWS
    assert len(envelope.items) == 1
    assert envelope.items[0].title == "OpenAI releases a new reasoning API"
    assert envelope.items[0].metadata["feed"] == "new"
    assert envelope.items[0].metadata["score"] == 500
    assert envelope.items[0].metadata["comment_count"] == 123
    assert envelope.items[0].metadata["url_domain"] == "openai.com"
    assert client.calls[0]["url"] == "https://hacker-news.firebaseio.com/v0/newstories.json"
    assert client.calls[1]["url"] == "https://hacker-news.firebaseio.com/v0/item/101.json"


def test_hacker_news_feed_search_falls_back_to_new_feed_for_unknown_feed() -> None:
    client = FakeJsonClient(payload=None, payloads=[[],])

    envelope = hacker_news_feed_search_tool(_context("agents", params={"feed": "frontpage"}), client=client)

    assert envelope.items == []
    assert envelope.errors == []
    assert envelope.metadata["feed"] == "new"
    assert client.calls[0]["url"] == "https://hacker-news.firebaseio.com/v0/newstories.json"


def test_hacker_news_feed_unexpected_payload_returns_structured_error() -> None:
    client = FakeJsonClient(payload={"not": "a feed"})

    envelope = hacker_news_feed_search_tool(_context("agents"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "hacker_news_feed_unexpected_payload"
    assert envelope.metadata["payload_type"] == "dict"


def test_source_tool_http_error_returns_retryable_tool_error() -> None:
    client = FakeJsonClient(
        payload=None,
        error=SourceHttpError(
            "rate limit exceeded",
            status_code=429,
            retryable=True,
            payload={"message": "rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0"},
        ),
    )

    envelope = github_repository_search_tool(_context("agents"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "http_429"
    assert envelope.errors[0].retryable is True
    assert envelope.rate_limit["x-ratelimit-remaining"] == "0"


def test_source_tool_unexpected_payload_returns_structured_error() -> None:
    client = FakeJsonClient(payload=[])

    envelope = github_repository_search_tool(_context("agents"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "unexpected_payload"
    assert envelope.errors[0].retryable is False
    assert envelope.metadata["payload_type"] == "list"
    assert "raw_payload" not in envelope.metadata


def test_source_tool_unexpected_items_payload_returns_structured_error() -> None:
    client = FakeJsonClient(payload={"total_count": 1, "items": None})

    envelope = github_repository_search_tool(_context("agents"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "unexpected_payload"
    assert envelope.errors[0].message == "Expected source payload shape: object.items array"


def test_arxiv_malformed_atom_returns_structured_error() -> None:
    client = FakeJsonClient(payload=None, text="<not atom")

    envelope = arxiv_search_tool(_context("agents"), client=client)

    assert envelope.items == []
    assert envelope.errors[0].code == "unexpected_payload"
    assert "raw_text" not in envelope.metadata


def test_source_tool_invalid_numeric_param_falls_back_to_default() -> None:
    client = FakeJsonClient(payload={"total_count": 0, "items": []})

    github_repository_search_tool(_context("agents", params={"per_page": "many"}), client=client)

    assert client.calls[0]["query_params"]["per_page"] == 10


def test_source_tool_invalid_timeout_param_falls_back_to_default() -> None:
    client = FakeJsonClient(payload={"total_count": 0, "items": []})

    github_repository_search_tool(_context("agents", params={"timeout_seconds": "eventually"}), client=client)

    assert client.calls[0]["timeout_seconds"] == 20


def test_default_registry_aligns_source_tools_with_scout_profiles() -> None:
    registry = create_default_tool_registry()
    code_names = {spec.name for spec in registry.list_for_agent(AgentRole.CODE_MODEL_SCOUT)}
    research_names = {spec.name for spec in registry.list_for_agent(AgentRole.RESEARCH_SCOUT)}

    assert {
        "github_repository_search",
        "github_code_search",
        "huggingface_model_search",
        "huggingface_dataset_search",
    }.issubset(code_names)
    assert "arxiv_search" not in code_names
    assert "openreview_note_search" not in code_names
    assert {
        "huggingface_model_search",
        "huggingface_dataset_search",
        "arxiv_search",
        "openreview_note_search",
    }.issubset(research_names)
    assert "github_repository_search" not in research_names
    assert "github_code_search" not in research_names
    assert registry.get("github_code_search").spec.source_type == SourceType.GITHUB


def test_default_registry_exposes_official_source_tools_to_official_scout() -> None:
    registry = create_default_tool_registry()
    official_names = {spec.name for spec in registry.list_for_agent(AgentRole.OFFICIAL_SCOUT)}
    code_names = {spec.name for spec in registry.list_for_agent(AgentRole.CODE_MODEL_SCOUT)}

    assert {"official_feed_search", "api_changelog_search"}.issubset(official_names)
    assert "official_feed_search" not in code_names
    assert registry.get("api_changelog_search").spec.source_type == SourceType.API_CHANGELOG


def test_default_registry_exposes_finance_source_tools_to_finance_scout() -> None:
    registry = create_default_tool_registry()
    finance_names = {spec.name for spec in registry.list_for_agent(AgentRole.FINANCE_SCOUT)}
    official_names = {spec.name for spec in registry.list_for_agent(AgentRole.OFFICIAL_SCOUT)}

    assert {"sec_company_filings", "sec_company_facts", "investor_relations_search"}.issubset(finance_names)
    assert "sec_company_filings" not in official_names
    assert registry.get("sec_company_facts").spec.source_type == SourceType.SEC_FILING


def test_default_registry_exposes_hacker_news_to_social_scout() -> None:
    registry = create_default_tool_registry()
    social_names = {spec.name for spec in registry.list_for_agent(AgentRole.SOCIAL_SCOUT)}
    finance_names = {spec.name for spec in registry.list_for_agent(AgentRole.FINANCE_SCOUT)}

    assert "hacker_news_feed_search" in social_names
    assert "hacker_news_feed_search" not in finance_names
    assert registry.get("hacker_news_feed_search").spec.source_type == SourceType.HACKER_NEWS


def test_source_tool_executor_persists_evidence_and_trace(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = create_default_tool_registry()
    fake_client = FakeJsonClient(
        payload={
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "id": 42,
                    "full_name": "openai/example-agents",
                    "html_url": "https://github.com/openai/example-agents",
                    "description": "Agent examples for a new API surface.",
                    "updated_at": "2026-07-03T12:00:00Z",
                    "owner": {"login": "openai"},
                }
            ],
        }
    )
    registry._tools["github_repository_search"] = registry._tools["github_repository_search"].__class__(
        spec=registry.require("github_repository_search").spec,
        func=lambda context: github_repository_search_tool(context, client=fake_client),
    )
    executor = ToolExecutor(db_session, registry=registry)

    result = executor.execute(
        tool_name="github_repository_search",
        context=_context("reasoning agents", params={"timeout_seconds": None}),
    )
    db_session.flush()

    assert result.tool_call.status == ToolCallStatus.SUCCEEDED
    assert fake_client.calls[0]["timeout_seconds"] == 20
    assert result.evidence_items[0].source_type == SourceType.GITHUB
    assert EvidenceRepository(db_session).require(result.evidence_items[0].id).title == "openai/example-agents"
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert len(timeline.events) == 2


def test_source_tool_executor_sanitizes_invalid_timeout(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = create_default_tool_registry()
    fake_client = FakeJsonClient(payload={"total_count": 0, "incomplete_results": False, "items": []})
    registry._tools["github_repository_search"] = registry._tools["github_repository_search"].__class__(
        spec=registry.require("github_repository_search").spec,
        func=lambda context: github_repository_search_tool(context, client=fake_client),
    )
    executor = ToolExecutor(db_session, registry=registry)

    executor.execute(
        tool_name="github_repository_search",
        context=_context("reasoning agents", params={"timeout_seconds": "eventually"}),
    )

    assert fake_client.calls[0]["timeout_seconds"] == 20


def _context(query: str, *, params: dict | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id=RUN_ID,
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.CODE_MODEL_SCOUT,
        query=query,
        params=params or {},
    )
