"""Real public-source tools for Connor.ai scouts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from app.config import get_settings
from app.domain import SourceType, ToolEnvelope, ToolEnvelopeItem, ToolError
from app.domain.base import utc_now
from app.tools.base import ToolExecutionContext
from app.tools.http import JsonHttpClient, SourceHttpError, selected_rate_limit


GITHUB_SEARCH_REPOSITORIES_URL = "https://api.github.com/search/repositories"
GITHUB_SEARCH_CODE_URL = "https://api.github.com/search/code"
HUGGINGFACE_MODELS_URL = "https://huggingface.co/api/models"
HUGGINGFACE_DATASETS_URL = "https://huggingface.co/api/datasets"
ARXIV_QUERY_URL = "https://export.arxiv.org/api/query"
OPENREVIEW_NOTES_URL = "https://api2.openreview.net/notes"

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
XML_NS = {
    **ATOM_NS,
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass(frozen=True)
class OfficialSource:
    key: str
    name: str
    url: str
    format: str
    homepage: str | None = None
    feed_item_kind: str = "official_feed_entry"
    html_item_kind: str = "official_changelog_page_section"


OFFICIAL_BLOG_FEEDS = {
    "openai_news": OfficialSource(
        key="openai_news",
        name="OpenAI News",
        url="https://openai.com/news/rss.xml",
        format="feed",
        homepage="https://openai.com/news/",
    ),
    "google_ai_blog": OfficialSource(
        key="google_ai_blog",
        name="Google AI Blog",
        url="https://blog.google/technology/ai/rss/",
        format="feed",
        homepage="https://blog.google/technology/ai/",
    ),
    "github_ai_blog": OfficialSource(
        key="github_ai_blog",
        name="GitHub AI and ML Blog",
        url="https://github.blog/ai-and-ml/feed/",
        format="feed",
        homepage="https://github.blog/ai-and-ml/",
    ),
    "huggingface_blog": OfficialSource(
        key="huggingface_blog",
        name="Hugging Face Blog",
        url="https://huggingface.co/blog/feed.xml",
        format="feed",
        homepage="https://huggingface.co/blog",
    ),
}

API_CHANGELOG_SOURCES = {
    "github_changelog": OfficialSource(
        key="github_changelog",
        name="GitHub Changelog",
        url="https://github.blog/changelog/feed/",
        format="feed",
        homepage="https://github.blog/changelog/",
    ),
    "openai_api_changelog": OfficialSource(
        key="openai_api_changelog",
        name="OpenAI API Changelog",
        url="https://developers.openai.com/api/docs/changelog",
        format="html_page",
        homepage="https://developers.openai.com/api/docs/changelog",
    ),
}

INVESTOR_RELATIONS_SOURCES = {
    "nvidia_financial_reports": OfficialSource(
        key="nvidia_financial_reports",
        name="NVIDIA Investor Relations Financial Reports",
        url="https://investor.nvidia.com/financial-info/financial-reports/default.aspx",
        format="html_page",
        homepage="https://investor.nvidia.com/",
        html_item_kind="investor_relations_page_section",
    ),
    "nvidia_ir_news": OfficialSource(
        key="nvidia_ir_news",
        name="NVIDIA Investor Relations News",
        url="https://investor.nvidia.com/news/press-release/default.aspx",
        format="html_page",
        homepage="https://investor.nvidia.com/news/press-release/default.aspx",
        html_item_kind="investor_relations_page_section",
    ),
    "amd_financial_results": OfficialSource(
        key="amd_financial_results",
        name="AMD Investor Relations Financial Results",
        url="https://ir.amd.com/financial-information/financial-results",
        format="html_page",
        homepage="https://ir.amd.com/",
        html_item_kind="investor_relations_page_section",
    ),
    "amd_ir_news": OfficialSource(
        key="amd_ir_news",
        name="AMD Investor Relations Press Releases",
        url="https://ir.amd.com/news-events/press-releases",
        format="html_page",
        homepage="https://ir.amd.com/news-events/press-releases",
        html_item_kind="investor_relations_page_section",
    ),
    "tsmc_ir_news": OfficialSource(
        key="tsmc_ir_news",
        name="TSMC Investor Relations News",
        url="https://investor.tsmc.com/english/ir-calendar",
        format="html_page",
        homepage="https://investor.tsmc.com/english",
        html_item_kind="investor_relations_page_section",
    ),
}

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_DEFAULT_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K")
SEC_DEFAULT_FACT_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "CostOfRevenue",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "CapitalExpenditures",
)
HACKER_NEWS_API_BASE_URL = "https://hacker-news.firebaseio.com/v0"
HACKER_NEWS_ITEM_URL_TEMPLATE = f"{HACKER_NEWS_API_BASE_URL}/item/{{item_id}}.json"
HACKER_NEWS_FEEDS = {
    "top": f"{HACKER_NEWS_API_BASE_URL}/topstories.json",
    "new": f"{HACKER_NEWS_API_BASE_URL}/newstories.json",
    "best": f"{HACKER_NEWS_API_BASE_URL}/beststories.json",
    "ask": f"{HACKER_NEWS_API_BASE_URL}/askstories.json",
    "show": f"{HACKER_NEWS_API_BASE_URL}/showstories.json",
    "job": f"{HACKER_NEWS_API_BASE_URL}/jobstories.json",
}
HACKER_NEWS_WEB_ITEM_URL = "https://news.ycombinator.com/item?id={item_id}"


def github_repository_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search public GitHub repositories and normalize results into evidence."""

    settings = get_settings()
    client = client or JsonHttpClient()
    per_page = _bounded_int(context.params.get("per_page"), default=10, minimum=1, maximum=30)
    query_params = {
        "q": context.query,
        "sort": context.params.get("sort", "updated"),
        "order": context.params.get("order", "desc"),
        "per_page": per_page,
        "page": _bounded_int(context.params.get("page"), default=1, minimum=1, maximum=10),
    }
    response = _request_json(
        client,
        GITHUB_SEARCH_REPOSITORIES_URL,
        query_params=query_params,
        headers=_github_headers(settings.github_token, settings.tool_user_agent),
        timeout_seconds=_timeout_seconds(context),
        tool_name="github_repository_search",
        source_type=SourceType.GITHUB,
        query=context.query,
    )
    if response.errors:
        return response

    payload = response.metadata["raw_payload"]
    if not isinstance(payload, dict):
        return _unexpected_payload_envelope(response, expected_shape="object")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return _unexpected_payload_envelope(response, expected_shape="object.items array")
    items = [_github_repo_item(item) for item in raw_items[:per_page] if isinstance(item, dict)]
    return response.model_copy(
        update={
            "items": items,
            "metadata": {
                "endpoint": GITHUB_SEARCH_REPOSITORIES_URL,
                "query_params": query_params,
                "total_count": payload.get("total_count"),
                "incomplete_results": payload.get("incomplete_results"),
            },
        }
    )


def github_code_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search public GitHub code results and normalize file hits into evidence."""

    settings = get_settings()
    client = client or JsonHttpClient()
    per_page = _bounded_int(context.params.get("per_page"), default=10, minimum=1, maximum=30)
    query_params = {
        "q": context.query,
        "sort": context.params.get("sort"),
        "order": context.params.get("order", "desc"),
        "per_page": per_page,
        "page": _bounded_int(context.params.get("page"), default=1, minimum=1, maximum=10),
    }
    response = _request_json(
        client,
        GITHUB_SEARCH_CODE_URL,
        query_params=query_params,
        headers=_github_headers(settings.github_token, settings.tool_user_agent),
        timeout_seconds=_timeout_seconds(context),
        tool_name="github_code_search",
        source_type=SourceType.GITHUB,
        query=context.query,
    )
    if response.errors:
        return response

    payload = response.metadata["raw_payload"]
    if not isinstance(payload, dict):
        return _unexpected_payload_envelope(response, expected_shape="object")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return _unexpected_payload_envelope(response, expected_shape="object.items array")
    items = [_github_code_item(item) for item in raw_items[:per_page] if isinstance(item, dict)]
    return response.model_copy(
        update={
            "items": items,
            "metadata": {
                "endpoint": GITHUB_SEARCH_CODE_URL,
                "query_params": query_params,
                "total_count": payload.get("total_count"),
                "incomplete_results": payload.get("incomplete_results"),
            },
        }
    )


def huggingface_model_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search public Hugging Face model repositories."""

    return _huggingface_search_tool(
        context,
        client=client,
        tool_name="huggingface_model_search",
        source_type=SourceType.HUGGING_FACE,
        endpoint=HUGGINGFACE_MODELS_URL,
        item_builder=_huggingface_model_item,
    )


def huggingface_dataset_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search public Hugging Face datasets."""

    return _huggingface_search_tool(
        context,
        client=client,
        tool_name="huggingface_dataset_search",
        source_type=SourceType.HUGGING_FACE,
        endpoint=HUGGINGFACE_DATASETS_URL,
        item_builder=_huggingface_dataset_item,
    )


def official_feed_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search curated official RSS/Atom blog feeds and normalize matching entries."""

    return _official_catalog_search_tool(
        context,
        client=client,
        tool_name="official_feed_search",
        source_type=SourceType.OFFICIAL_BLOG,
        catalog=OFFICIAL_BLOG_FEEDS,
        default_source_keys=tuple(OFFICIAL_BLOG_FEEDS),
    )


def api_changelog_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search curated official API changelog feeds/pages and normalize matching entries."""

    return _official_catalog_search_tool(
        context,
        client=client,
        tool_name="api_changelog_search",
        source_type=SourceType.API_CHANGELOG,
        catalog=API_CHANGELOG_SOURCES,
        default_source_keys=tuple(API_CHANGELOG_SOURCES),
    )


def sec_company_filings_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Fetch recent SEC EDGAR submissions for one company by ticker or CIK."""

    settings = get_settings()
    client = client or JsonHttpClient()
    retrieved_at = utc_now()
    headers = _sec_headers(settings.sec_user_agent or settings.tool_user_agent)
    company, resolve_errors, resolve_metadata = _resolve_sec_company(context, client=client, headers=headers)
    if resolve_errors:
        return ToolEnvelope(
            tool_name="sec_company_filings",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=resolve_errors,
            metadata=resolve_metadata,
        )

    cik = company["cik"]
    submissions_url = SEC_SUBMISSIONS_URL_TEMPLATE.format(cik=cik)
    payload, request_error = _sec_json_payload(
        client,
        submissions_url,
        headers=headers,
        timeout_seconds=_timeout_seconds(context),
        error_prefix="sec_submissions",
    )
    if request_error is not None:
        return ToolEnvelope(
            tool_name="sec_company_filings",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[request_error],
            metadata={
                **resolve_metadata,
                "endpoint": submissions_url,
                "company": company,
            },
        )
    if not isinstance(payload, dict):
        return ToolEnvelope(
            tool_name="sec_company_filings",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[
                ToolError(
                    code="sec_submissions_unexpected_payload",
                    message="Expected SEC submissions payload object",
                    retryable=False,
                )
            ],
            metadata={
                **resolve_metadata,
                "endpoint": submissions_url,
                "payload_type": type(payload).__name__,
                "company": company,
            },
        )

    forms = {form.upper() for form in _string_list(context.params.get("forms"), default=SEC_DEFAULT_FORMS)}
    max_results = _bounded_int(context.params.get("max_results"), default=10, minimum=1, maximum=50)
    rows = [
        row
        for row in _sec_recent_filing_rows(payload)
        if not forms or str(row.get("form", "")).upper() in forms
    ][:max_results]
    items = [
        _sec_filing_item(
            row,
            cik=cik,
            company_name=str(payload.get("name") or company.get("title") or ""),
            ticker=company.get("ticker"),
        )
        for row in rows
    ]
    return ToolEnvelope(
        tool_name="sec_company_filings",
        source_type=SourceType.SEC_FILING,
        query=context.query,
        retrieved_at=retrieved_at,
        items=items,
        metadata={
            **resolve_metadata,
            "endpoint": submissions_url,
            "company": {
                **company,
                "name": payload.get("name") or company.get("title"),
                "tickers": payload.get("tickers"),
            },
            "forms": sorted(forms),
            "result_count": len(items),
        },
    )


def sec_company_facts_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Fetch selected SEC XBRL company facts for one company by ticker or CIK."""

    settings = get_settings()
    client = client or JsonHttpClient()
    retrieved_at = utc_now()
    headers = _sec_headers(settings.sec_user_agent or settings.tool_user_agent)
    company, resolve_errors, resolve_metadata = _resolve_sec_company(context, client=client, headers=headers)
    if resolve_errors:
        return ToolEnvelope(
            tool_name="sec_company_facts",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=resolve_errors,
            metadata=resolve_metadata,
        )

    cik = company["cik"]
    facts_url = SEC_COMPANY_FACTS_URL_TEMPLATE.format(cik=cik)
    payload, request_error = _sec_json_payload(
        client,
        facts_url,
        headers=headers,
        timeout_seconds=_timeout_seconds(context),
        error_prefix="sec_companyfacts",
    )
    if request_error is not None:
        return ToolEnvelope(
            tool_name="sec_company_facts",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[request_error],
            metadata={
                **resolve_metadata,
                "endpoint": facts_url,
                "company": company,
            },
        )
    if not isinstance(payload, dict):
        return ToolEnvelope(
            tool_name="sec_company_facts",
            source_type=SourceType.SEC_FILING,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[
                ToolError(
                    code="sec_companyfacts_unexpected_payload",
                    message="Expected SEC companyfacts payload object",
                    retryable=False,
                )
            ],
            metadata={
                **resolve_metadata,
                "endpoint": facts_url,
                "payload_type": type(payload).__name__,
                "company": company,
            },
        )

    concepts = _string_list(context.params.get("concepts"), default=SEC_DEFAULT_FACT_CONCEPTS)
    forms = {form.upper() for form in _string_list(context.params.get("forms"), default=("10-K", "10-Q", "20-F", "40-F"))}
    unit_filter = str(context.params.get("unit", "USD"))
    max_results = _bounded_int(context.params.get("max_results"), default=10, minimum=1, maximum=50)
    fact_rows = _sec_fact_rows(payload, concepts=concepts, forms=forms, unit_filter=unit_filter)
    items = [
        _sec_fact_item(
            row,
            cik=cik,
            company_name=str(payload.get("entityName") or company.get("title") or ""),
            ticker=company.get("ticker"),
        )
        for row in fact_rows[:max_results]
    ]
    return ToolEnvelope(
        tool_name="sec_company_facts",
        source_type=SourceType.SEC_FILING,
        query=context.query,
        retrieved_at=retrieved_at,
        items=items,
        metadata={
            **resolve_metadata,
            "endpoint": facts_url,
            "company": {
                **company,
                "name": payload.get("entityName") or company.get("title"),
            },
            "concepts": concepts,
            "forms": sorted(forms),
            "unit": unit_filter,
            "result_count": len(items),
        },
    )


def investor_relations_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search curated company investor-relations pages for earnings and guidance signals."""

    return _official_catalog_search_tool(
        context,
        client=client,
        tool_name="investor_relations_search",
        source_type=SourceType.INVESTOR_RELATIONS,
        catalog=INVESTOR_RELATIONS_SOURCES,
        default_source_keys=tuple(INVESTOR_RELATIONS_SOURCES),
    )


def hacker_news_feed_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search bounded Hacker News official API story feeds and normalize matching items."""

    settings = get_settings()
    client = client or JsonHttpClient()
    retrieved_at = utc_now()
    feed = _hacker_news_feed(context.params.get("feed", "new"))
    feed_url = HACKER_NEWS_FEEDS[feed]
    fetch_limit = _bounded_int(context.params.get("fetch_limit"), default=30, minimum=1, maximum=100)
    max_results = _bounded_int(context.params.get("max_results"), default=10, minimum=1, maximum=50)
    match_mode = _match_mode(context.params.get("match_mode"))
    headers = _public_headers(settings.tool_user_agent, accept="application/json")
    payload, request_error = _json_payload(
        client,
        feed_url,
        headers=headers,
        timeout_seconds=_timeout_seconds(context),
        error_prefix="hacker_news_feed",
    )
    if request_error is not None:
        return ToolEnvelope(
            tool_name="hacker_news_feed_search",
            source_type=SourceType.HACKER_NEWS,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[request_error],
            metadata={
                "feed": feed,
                "endpoint": feed_url,
                "fetch_limit": fetch_limit,
                "max_results": max_results,
            },
        )
    if not isinstance(payload, list):
        return ToolEnvelope(
            tool_name="hacker_news_feed_search",
            source_type=SourceType.HACKER_NEWS,
            query=context.query,
            retrieved_at=retrieved_at,
            errors=[
                ToolError(
                    code="hacker_news_feed_unexpected_payload",
                    message="Expected Hacker News feed payload array",
                    retryable=False,
                )
            ],
            metadata={
                "feed": feed,
                "endpoint": feed_url,
                "payload_type": type(payload).__name__,
            },
        )

    errors: list[ToolError] = []
    items: list[ToolEnvelopeItem] = []
    attempted_ids = [item_id for item_id in payload[:fetch_limit] if isinstance(item_id, int)]
    for item_id in attempted_ids:
        item_payload, item_error = _json_payload(
            client,
            HACKER_NEWS_ITEM_URL_TEMPLATE.format(item_id=item_id),
            headers=headers,
            timeout_seconds=_timeout_seconds(context),
            error_prefix=f"hacker_news_item_{item_id}",
        )
        if item_error is not None:
            errors.append(item_error)
            continue
        if not isinstance(item_payload, dict):
            errors.append(
                ToolError(
                    code=f"hacker_news_item_{item_id}_unexpected_payload",
                    message="Expected Hacker News item payload object",
                    retryable=False,
                )
            )
            continue
        normalized = _hacker_news_item(item_payload, feed=feed)
        if normalized is None:
            continue
        if not _matches_query(
            f"{normalized.title} {normalized.snippet} {normalized.metadata.get('url_domain', '')}",
            query=context.query,
            match_mode=match_mode,
        ):
            continue
        items.append(normalized)
        if len(items) >= max_results:
            break

    return ToolEnvelope(
        tool_name="hacker_news_feed_search",
        source_type=SourceType.HACKER_NEWS,
        query=context.query,
        retrieved_at=retrieved_at,
        items=items,
        errors=errors,
        metadata={
            "feed": feed,
            "endpoint": feed_url,
            "fetch_limit": fetch_limit,
            "max_results": max_results,
            "match_mode": match_mode,
            "attempted_item_ids": attempted_ids,
            "result_count": len(items),
            "available_feeds": sorted(HACKER_NEWS_FEEDS),
        },
    )


def arxiv_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search arXiv's public Atom API and normalize paper entries."""

    settings = get_settings()
    client = client or JsonHttpClient()
    max_results = _bounded_int(context.params.get("max_results"), default=10, minimum=1, maximum=50)
    search_query = context.params.get("search_query") or _arxiv_search_query(context.query)
    query_params = {
        "search_query": search_query,
        "start": _bounded_int(context.params.get("start"), default=0, minimum=0, maximum=1000),
        "max_results": max_results,
        "sortBy": context.params.get("sortBy", "submittedDate"),
        "sortOrder": context.params.get("sortOrder", "descending"),
    }
    response = _request_text(
        client,
        ARXIV_QUERY_URL,
        query_params=query_params,
        headers=_public_headers(settings.tool_user_agent, accept="application/atom+xml"),
        timeout_seconds=_timeout_seconds(context),
        tool_name="arxiv_search",
        source_type=SourceType.ARXIV,
        query=context.query,
    )
    if response.errors:
        return response

    raw_text = response.metadata["raw_text"]
    try:
        root = ElementTree.fromstring(raw_text)
    except ElementTree.ParseError:
        return _unexpected_payload_envelope(response, expected_shape="atom feed")

    entries = root.findall("atom:entry", ATOM_NS)
    items = [_arxiv_item(entry) for entry in entries[:max_results]]
    return response.model_copy(
        update={
            "items": items,
            "metadata": {
                "endpoint": ARXIV_QUERY_URL,
                "query_params": query_params,
                "total_results": _xml_text(root, "opensearch:totalResults"),
                "start_index": _xml_text(root, "opensearch:startIndex"),
                "items_per_page": _xml_text(root, "opensearch:itemsPerPage"),
                "result_count": len(items),
            },
        }
    )


def openreview_note_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None = None,
) -> ToolEnvelope:
    """Search OpenReview API 2 notes by title and optional filters."""

    settings = get_settings()
    client = client or JsonHttpClient()
    limit = _bounded_int(context.params.get("limit"), default=10, minimum=1, maximum=50)
    query_params = {
        "content.title": context.params.get("content.title", context.query),
        "limit": limit,
        "offset": _bounded_int(context.params.get("offset"), default=0, minimum=0, maximum=1000),
        "sort": context.params.get("sort", "tmdate:desc"),
    }
    for key in [
        "id",
        "forum",
        "replyto",
        "invitation",
        "invitations",
        "content.venue",
        "content.venueid",
        "content.venue_id",
        "content.authorids",
    ]:
        if context.params.get(key) is not None:
            query_params[key] = context.params[key]

    response = _request_json(
        client,
        OPENREVIEW_NOTES_URL,
        query_params=query_params,
        headers=_public_headers(settings.tool_user_agent, accept="application/json"),
        timeout_seconds=_timeout_seconds(context),
        tool_name="openreview_note_search",
        source_type=SourceType.OPENREVIEW,
        query=context.query,
    )
    if response.errors:
        return response

    payload = response.metadata["raw_payload"]
    if not isinstance(payload, dict):
        return _unexpected_payload_envelope(response, expected_shape="object")
    raw_notes = payload.get("notes")
    if not isinstance(raw_notes, list):
        return _unexpected_payload_envelope(response, expected_shape="object.notes array")
    items = [_openreview_note_item(note) for note in raw_notes[:limit] if isinstance(note, dict)]
    return response.model_copy(
        update={
            "items": items,
            "metadata": {
                "endpoint": OPENREVIEW_NOTES_URL,
                "query_params": query_params,
                "count": payload.get("count"),
                "result_count": len(items),
            },
        }
    )


def _huggingface_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None,
    tool_name: str,
    source_type: SourceType,
    endpoint: str,
    item_builder,
) -> ToolEnvelope:
    settings = get_settings()
    client = client or JsonHttpClient()
    limit = _bounded_int(context.params.get("limit"), default=10, minimum=1, maximum=50)
    query_params = {
        "search": context.query,
        "sort": context.params.get("sort", "lastModified"),
        "direction": context.params.get("direction", -1),
        "limit": limit,
        "full": context.params.get("full", False),
    }
    response = _request_json(
        client,
        endpoint,
        query_params=query_params,
        headers=_huggingface_headers(settings.huggingface_token, settings.tool_user_agent),
        timeout_seconds=_timeout_seconds(context),
        tool_name=tool_name,
        source_type=source_type,
        query=context.query,
    )
    if response.errors:
        return response

    payload = response.metadata["raw_payload"]
    if not isinstance(payload, list):
        return _unexpected_payload_envelope(response, expected_shape="array")
    raw_items = payload
    items = [item_builder(item) for item in raw_items[:limit] if isinstance(item, dict)]
    return response.model_copy(
        update={
            "items": items,
            "metadata": {
                "endpoint": endpoint,
                "query_params": query_params,
                "result_count": len(items),
            },
        }
    )


def _official_catalog_search_tool(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient | None,
    tool_name: str,
    source_type: SourceType,
    catalog: dict[str, OfficialSource],
    default_source_keys: tuple[str, ...],
) -> ToolEnvelope:
    settings = get_settings()
    client = client or JsonHttpClient()
    retrieved_at = utc_now()
    selected_keys, unknown_keys = _selected_source_keys(
        context.params,
        catalog=catalog,
        default_source_keys=default_source_keys,
    )
    max_results = _bounded_int(context.params.get("max_results"), default=10, minimum=1, maximum=50)
    match_mode = _match_mode(context.params.get("match_mode"))
    errors = [
        ToolError(
            code="unknown_source_key",
            message=f"Unknown source key: {key}",
            retryable=False,
        )
        for key in unknown_keys
    ]
    items: list[ToolEnvelopeItem] = []
    source_results: list[dict[str, Any]] = []

    for key in selected_keys:
        source = catalog[key]
        try:
            response = client.get_text(
                source.url,
                query_params={},
                headers=_public_headers(
                    settings.tool_user_agent,
                    accept="application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9",
                ),
                timeout_seconds=_timeout_seconds(context),
            )
        except SourceHttpError as exc:
            errors.append(
                ToolError(
                    code=f"{key}_http_{exc.status_code}" if exc.status_code else f"{key}_http_error",
                    message=str(exc) or f"HTTP request failed for {source.name}",
                    retryable=exc.retryable,
                )
            )
            source_results.append(
                {
                    "source_key": key,
                    "source_name": source.name,
                    "url": source.url,
                    "status": "failed",
                    "error_payload": exc.payload,
                }
            )
            continue

        normalized_items, parse_error = _official_source_items(
            source,
            response.text,
            query=context.query,
            match_mode=match_mode,
        )
        if parse_error is not None:
            errors.append(parse_error)
            source_results.append(
                {
                    "source_key": key,
                    "source_name": source.name,
                    "url": source.url,
                    "status": "unexpected_payload",
                    "status_code": response.status_code,
                }
            )
            continue

        items.extend(normalized_items)
        source_results.append(
            {
                "source_key": key,
                "source_name": source.name,
                "url": source.url,
                "status": "succeeded",
                "status_code": response.status_code,
                "item_count": len(normalized_items),
            }
        )

    items = sorted(
        items,
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:max_results]
    return ToolEnvelope(
        tool_name=tool_name,
        source_type=source_type,
        query=context.query,
        retrieved_at=retrieved_at,
        items=items,
        errors=errors,
        metadata={
            "source_keys": selected_keys,
            "unknown_source_keys": unknown_keys,
            "max_results": max_results,
            "match_mode": match_mode,
            "source_results": source_results,
            "result_count": len(items),
            "available_source_keys": sorted(catalog),
        },
    )


def _request_json(
    client: JsonHttpClient,
    url: str,
    *,
    query_params: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
    tool_name: str,
    source_type: SourceType,
    query: str,
) -> ToolEnvelope:
    retrieved_at = utc_now()
    try:
        response = client.get_json(
            url,
            query_params=query_params,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
    except SourceHttpError as exc:
        return ToolEnvelope(
            tool_name=tool_name,
            source_type=source_type,
            query=query,
            retrieved_at=retrieved_at,
            errors=[
                ToolError(
                    code=f"http_{exc.status_code}" if exc.status_code else "http_error",
                    message=str(exc) or "HTTP request failed",
                    retryable=exc.retryable,
                )
            ],
            rate_limit=selected_rate_limit(exc.headers, prefix="x-ratelimit"),
            metadata={
                "endpoint": url,
                "query_params": query_params,
                "error_payload": exc.payload,
            },
        )

    return ToolEnvelope(
        tool_name=tool_name,
        source_type=source_type,
        query=query,
        retrieved_at=retrieved_at,
        rate_limit=selected_rate_limit(response.headers, prefix="x-ratelimit"),
        metadata={
            "endpoint": url,
            "query_params": query_params,
            "status_code": response.status_code,
            "response_url": response.url,
            "raw_payload": response.payload,
        },
    )


def _request_text(
    client: JsonHttpClient,
    url: str,
    *,
    query_params: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
    tool_name: str,
    source_type: SourceType,
    query: str,
) -> ToolEnvelope:
    retrieved_at = utc_now()
    try:
        response = client.get_text(
            url,
            query_params=query_params,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
    except SourceHttpError as exc:
        return ToolEnvelope(
            tool_name=tool_name,
            source_type=source_type,
            query=query,
            retrieved_at=retrieved_at,
            errors=[
                ToolError(
                    code=f"http_{exc.status_code}" if exc.status_code else "http_error",
                    message=str(exc) or "HTTP request failed",
                    retryable=exc.retryable,
                )
            ],
            rate_limit=selected_rate_limit(exc.headers, prefix="x-ratelimit"),
            metadata={
                "endpoint": url,
                "query_params": query_params,
                "error_payload": exc.payload,
            },
        )

    return ToolEnvelope(
        tool_name=tool_name,
        source_type=source_type,
        query=query,
        retrieved_at=retrieved_at,
        rate_limit=selected_rate_limit(response.headers, prefix="x-ratelimit"),
        metadata={
            "endpoint": url,
            "query_params": query_params,
            "status_code": response.status_code,
            "response_url": response.url,
            "raw_text": response.text,
        },
    )


def _github_repo_item(item: dict[str, Any]) -> ToolEnvelopeItem:
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    topics = item.get("topics") if isinstance(item.get("topics"), list) else []
    title = item.get("full_name") or item.get("name") or "GitHub repository result"
    description = item.get("description") or "No repository description provided."
    updated_at = _parse_datetime(item.get("updated_at"))
    metadata = {
        "kind": "repository",
        "repository": item.get("full_name"),
        "language": item.get("language"),
        "stars": item.get("stargazers_count"),
        "forks": item.get("forks_count"),
        "topics": topics,
        "license": (item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), dict) else None,
    }
    return ToolEnvelopeItem(
        title=title,
        url=item.get("html_url"),
        author=owner.get("login"),
        published_at=updated_at,
        snippet=description,
        raw_ref=str(item.get("id")) if item.get("id") is not None else item.get("node_id"),
        raw_hash=_stable_hash(item),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _github_code_item(item: dict[str, Any]) -> ToolEnvelopeItem:
    repository = item.get("repository") if isinstance(item.get("repository"), dict) else {}
    owner = repository.get("owner") if isinstance(repository.get("owner"), dict) else {}
    repo_name = repository.get("full_name")
    path = item.get("path") or item.get("name") or "code result"
    title = f"{repo_name}:{path}" if repo_name else path
    snippet = f"GitHub code search match in {title}."
    metadata = {
        "kind": "code",
        "repository": repo_name,
        "path": item.get("path"),
        "sha": item.get("sha"),
        "git_url": item.get("git_url"),
    }
    return ToolEnvelopeItem(
        title=title,
        url=item.get("html_url"),
        author=owner.get("login"),
        snippet=snippet,
        raw_ref=item.get("sha") or item.get("url"),
        raw_hash=_stable_hash(item),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _huggingface_model_item(item: dict[str, Any]) -> ToolEnvelopeItem:
    model_id = item.get("modelId") or item.get("id") or "Hugging Face model result"
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    downloads = item.get("downloads")
    likes = item.get("likes")
    snippet_parts = [f"Model repository {model_id}"]
    if tags:
        snippet_parts.append(f"tags: {', '.join(str(tag) for tag in tags[:8])}")
    if downloads is not None:
        snippet_parts.append(f"downloads: {downloads}")
    metadata = {
        "kind": "model",
        "model_id": model_id,
        "pipeline_tag": item.get("pipeline_tag"),
        "library_name": item.get("library_name"),
        "tags": tags,
        "downloads": downloads,
        "likes": likes,
        "last_modified": item.get("lastModified"),
    }
    return ToolEnvelopeItem(
        title=model_id,
        url=f"https://huggingface.co/{model_id}",
        author=str(model_id).split("/", 1)[0] if "/" in str(model_id) else None,
        published_at=_parse_datetime(item.get("lastModified")),
        snippet="; ".join(snippet_parts),
        raw_ref=model_id,
        raw_hash=_stable_hash(item),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _huggingface_dataset_item(item: dict[str, Any]) -> ToolEnvelopeItem:
    dataset_id = item.get("id") or "Hugging Face dataset result"
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    snippet_parts = [f"Dataset repository {dataset_id}"]
    if tags:
        snippet_parts.append(f"tags: {', '.join(str(tag) for tag in tags[:8])}")
    metadata = {
        "kind": "dataset",
        "dataset_id": dataset_id,
        "tags": tags,
        "downloads": item.get("downloads"),
        "likes": item.get("likes"),
        "last_modified": item.get("lastModified"),
    }
    return ToolEnvelopeItem(
        title=dataset_id,
        url=f"https://huggingface.co/datasets/{dataset_id}",
        author=str(dataset_id).split("/", 1)[0] if "/" in str(dataset_id) else None,
        published_at=_parse_datetime(item.get("lastModified")),
        snippet="; ".join(snippet_parts),
        raw_ref=dataset_id,
        raw_hash=_stable_hash(item),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _arxiv_item(entry: ElementTree.Element) -> ToolEnvelopeItem:
    title = _normalize_space(_xml_text(entry, "atom:title") or "arXiv paper result")
    abstract = _normalize_space(_xml_text(entry, "atom:summary") or "")
    abs_url = _xml_text(entry, "atom:id")
    published_at = _parse_datetime(_xml_text(entry, "atom:published"))
    updated_at = _parse_datetime(_xml_text(entry, "atom:updated"))
    authors = [
        _normalize_space(_xml_text(author, "atom:name") or "")
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    authors = [author for author in authors if author]
    categories = [
        category.attrib.get("term")
        for category in entry.findall("atom:category", ATOM_NS)
        if category.attrib.get("term")
    ]
    pdf_url = None
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href")
            break
    raw_payload = {
        "id": abs_url,
        "title": title,
        "summary": abstract,
        "published": _xml_text(entry, "atom:published"),
        "updated": _xml_text(entry, "atom:updated"),
        "authors": authors,
        "categories": categories,
    }
    metadata = {
        "kind": "paper",
        "arxiv_id": _arxiv_id(abs_url),
        "authors": authors,
        "categories": categories,
        "primary_category": _xml_attr(entry, "arxiv:primary_category", "term"),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "pdf_url": pdf_url,
        "comment": _xml_text(entry, "arxiv:comment"),
        "journal_ref": _xml_text(entry, "arxiv:journal_ref"),
        "doi": _xml_text(entry, "arxiv:doi"),
    }
    return ToolEnvelopeItem(
        title=title,
        url=abs_url,
        author=", ".join(authors[:5]) if authors else None,
        published_at=published_at,
        snippet=abstract,
        raw_ref=_arxiv_id(abs_url) or abs_url,
        raw_hash=_stable_hash(raw_payload),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _openreview_note_item(note: dict[str, Any]) -> ToolEnvelopeItem:
    content = note.get("content") if isinstance(note.get("content"), dict) else {}
    title = _content_value(content, "title") or note.get("id") or "OpenReview note result"
    abstract = _content_value(content, "abstract") or _content_value(content, "summary") or ""
    authors = _content_value(content, "authors") or []
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list):
        authors = []
    venue = (
        _content_value(content, "venue")
        or _content_value(content, "venueid")
        or _content_value(content, "venue_id")
    )
    note_id = note.get("id")
    metadata = {
        "kind": "note",
        "note_id": note_id,
        "forum": note.get("forum"),
        "replyto": note.get("replyto"),
        "invitation": note.get("invitation"),
        "venue": venue,
        "authors": authors,
        "number": note.get("number"),
        "cdate": note.get("cdate"),
        "mdate": note.get("mdate"),
        "tmdate": note.get("tmdate"),
    }
    return ToolEnvelopeItem(
        title=str(title),
        url=f"https://openreview.net/forum?id={note_id}" if note_id else None,
        author=", ".join(str(author) for author in authors[:5]) if authors else None,
        published_at=_parse_openreview_time(note.get("pdate") or note.get("cdate")),
        snippet=_normalize_space(str(abstract)),
        raw_ref=note_id,
        raw_hash=_stable_hash(note),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _resolve_sec_company(
    context: ToolExecutionContext,
    *,
    client: JsonHttpClient,
    headers: dict[str, str],
) -> tuple[dict[str, Any], list[ToolError], dict[str, Any]]:
    cik = _normalize_cik(context.params.get("cik"))
    ticker = _sec_ticker_from_context(context)
    if cik:
        return (
            {
                "cik": cik,
                "ticker": ticker,
                "title": context.params.get("company_name"),
            },
            [],
            {"resolution": "cik"},
        )
    if not ticker:
        return (
            {},
            [
                ToolError(
                    code="missing_company_identifier",
                    message="SEC tools require params.cik or params.ticker",
                    retryable=False,
                )
            ],
            {"resolution": "missing_company_identifier"},
        )

    payload, request_error = _sec_json_payload(
        client,
        SEC_COMPANY_TICKERS_URL,
        headers=headers,
        timeout_seconds=_timeout_seconds(context),
        error_prefix="sec_ticker_map",
    )
    if request_error is not None:
        return {}, [request_error], {"resolution": "ticker_map_failed", "ticker": ticker}
    if not isinstance(payload, dict):
        return (
            {},
            [
                ToolError(
                    code="sec_ticker_map_unexpected_payload",
                    message="Expected SEC ticker map payload object",
                    retryable=False,
                )
            ],
            {"resolution": "ticker_map_unexpected_payload", "ticker": ticker},
        )

    normalized_ticker = ticker.upper()
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker", "")).upper() != normalized_ticker:
            continue
        resolved_cik = _normalize_cik(item.get("cik_str"))
        if not resolved_cik:
            break
        return (
            {
                "cik": resolved_cik,
                "ticker": normalized_ticker,
                "title": item.get("title"),
            },
            [],
            {"resolution": "ticker", "ticker": normalized_ticker},
        )

    return (
        {},
        [
            ToolError(
                code="ticker_not_found",
                message=f"Ticker was not found in SEC company tickers: {normalized_ticker}",
                retryable=False,
            )
        ],
        {"resolution": "ticker_not_found", "ticker": normalized_ticker},
    )


def _sec_json_payload(
    client: JsonHttpClient,
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: int,
    error_prefix: str,
) -> tuple[Any | None, ToolError | None]:
    return _json_payload(
        client,
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
        error_prefix=error_prefix,
        default_message="SEC HTTP request failed",
    )


def _json_payload(
    client: JsonHttpClient,
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: int,
    error_prefix: str,
    default_message: str = "HTTP request failed",
) -> tuple[Any | None, ToolError | None]:
    try:
        response = client.get_json(
            url,
            query_params={},
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
    except SourceHttpError as exc:
        return (
            None,
            ToolError(
                code=f"{error_prefix}_http_{exc.status_code}" if exc.status_code else f"{error_prefix}_http_error",
                message=str(exc) or default_message,
                retryable=exc.retryable,
            ),
        )
    return response.payload, None


def _sec_recent_filing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    filings = payload.get("filings") if isinstance(payload.get("filings"), dict) else {}
    recent = filings.get("recent") if isinstance(filings.get("recent"), dict) else {}
    accession_numbers = recent.get("accessionNumber") if isinstance(recent.get("accessionNumber"), list) else []
    rows: list[dict[str, Any]] = []
    for index, accession_number in enumerate(accession_numbers):
        row = {
            key: values[index] if isinstance(values, list) and index < len(values) else None
            for key, values in recent.items()
        }
        row["accessionNumber"] = accession_number
        rows.append(row)
    return rows


def _sec_filing_item(
    row: dict[str, Any],
    *,
    cik: str,
    company_name: str,
    ticker: str | None,
) -> ToolEnvelopeItem:
    form = str(row.get("form") or "SEC filing")
    filing_date = str(row.get("filingDate") or "")
    primary_document = row.get("primaryDocument")
    accession_number = row.get("accessionNumber")
    company_label = ticker or company_name or f"CIK {cik}"
    title = f"{company_label} {form} filed {filing_date}".strip()
    doc_description = row.get("primaryDocDescription") or primary_document or form
    snippet = (
        f"SEC EDGAR filing {form} for {company_name or company_label}; "
        f"primary document: {doc_description}; report date: {row.get('reportDate') or 'n/a'}."
    )
    metadata = {
        "kind": "sec_filing",
        "cik": cik,
        "ticker": ticker,
        "company_name": company_name,
        "form": form,
        "accession_number": accession_number,
        "filing_date": filing_date,
        "report_date": row.get("reportDate"),
        "acceptance_datetime": row.get("acceptanceDateTime"),
        "primary_document": primary_document,
        "primary_doc_description": row.get("primaryDocDescription"),
        "is_xbrl": row.get("isXBRL"),
        "is_inline_xbrl": row.get("isInlineXBRL"),
        "size": row.get("size"),
    }
    return ToolEnvelopeItem(
        title=title,
        url=_sec_filing_url(cik, accession_number, primary_document),
        author="SEC EDGAR",
        published_at=_parse_sec_date(filing_date),
        snippet=snippet,
        raw_ref=accession_number,
        raw_hash=_stable_hash(row),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _sec_fact_rows(
    payload: dict[str, Any],
    *,
    concepts: list[str],
    forms: set[str],
    unit_filter: str,
) -> list[dict[str, Any]]:
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    rows: list[dict[str, Any]] = []
    for taxonomy, taxonomy_facts in facts.items():
        if not isinstance(taxonomy_facts, dict):
            continue
        for concept in concepts:
            concept_payload = taxonomy_facts.get(concept)
            if not isinstance(concept_payload, dict):
                continue
            units = concept_payload.get("units") if isinstance(concept_payload.get("units"), dict) else {}
            for unit, unit_rows in units.items():
                if unit_filter and unit != unit_filter:
                    continue
                if not isinstance(unit_rows, list):
                    continue
                for row in unit_rows:
                    if not isinstance(row, dict):
                        continue
                    form = str(row.get("form") or "").upper()
                    if forms and form not in forms:
                        continue
                    rows.append(
                        {
                            **row,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "label": concept_payload.get("label") or concept,
                            "description": concept_payload.get("description"),
                            "unit": unit,
                        }
                    )
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("filed") or ""),
            str(row.get("end") or ""),
            str(row.get("fy") or ""),
            str(row.get("fp") or ""),
        ),
        reverse=True,
    )


def _sec_fact_item(
    row: dict[str, Any],
    *,
    cik: str,
    company_name: str,
    ticker: str | None,
) -> ToolEnvelopeItem:
    label = str(row.get("label") or row.get("concept") or "SEC XBRL fact")
    value = row.get("val")
    unit = row.get("unit")
    fy = row.get("fy")
    fp = row.get("fp")
    form = row.get("form")
    company_label = ticker or company_name or f"CIK {cik}"
    title = f"{company_label} {label} {fy or ''} {fp or ''}".strip()
    snippet = (
        f"SEC XBRL fact {label}: {value} {unit}; form {form}; "
        f"period ended {row.get('end') or 'n/a'}; filed {row.get('filed') or 'n/a'}."
    )
    metadata = {
        "kind": "sec_xbrl_fact",
        "cik": cik,
        "ticker": ticker,
        "company_name": company_name,
        "taxonomy": row.get("taxonomy"),
        "concept": row.get("concept"),
        "label": label,
        "description": row.get("description"),
        "unit": unit,
        "value": value,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": row.get("filed"),
        "period_end": row.get("end"),
        "accession_number": row.get("accn"),
        "frame": row.get("frame"),
    }
    return ToolEnvelopeItem(
        title=title,
        url=_sec_accession_url(cik, row.get("accn")),
        author="SEC EDGAR XBRL",
        published_at=_parse_sec_date(row.get("filed")),
        snippet=snippet,
        raw_ref=f"{row.get('concept')}:{row.get('accn')}:{row.get('end')}:{row.get('fp')}",
        raw_hash=_stable_hash(row),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _hacker_news_item(item: dict[str, Any], *, feed: str) -> ToolEnvelopeItem | None:
    if item.get("deleted") or item.get("dead"):
        return None
    item_id = item.get("id")
    item_type = item.get("type")
    if item_type not in {"story", "job", "poll"}:
        return None
    title = _html_fragment_text(str(item.get("title") or f"Hacker News item {item_id}"))
    text = _html_fragment_text(str(item.get("text") or ""))
    external_url = item.get("url") if isinstance(item.get("url"), str) else None
    hn_url = HACKER_NEWS_WEB_ITEM_URL.format(item_id=item_id)
    snippet_parts = []
    if text:
        snippet_parts.append(text)
    if external_url:
        snippet_parts.append(f"External link: {external_url}")
    if item.get("score") is not None:
        snippet_parts.append(f"score: {item.get('score')}")
    if item.get("descendants") is not None:
        snippet_parts.append(f"comments: {item.get('descendants')}")
    snippet = "; ".join(snippet_parts) or f"Hacker News {item_type} item from {feed} feed."
    metadata = {
        "kind": "hacker_news_item",
        "feed": feed,
        "item_id": item_id,
        "item_type": item_type,
        "score": item.get("score"),
        "comment_count": item.get("descendants"),
        "external_url": external_url,
        "hn_url": hn_url,
        "url_domain": _url_domain(external_url),
        "kid_count": len(item.get("kids") or []) if isinstance(item.get("kids"), list) else 0,
    }
    return ToolEnvelopeItem(
        title=title,
        url=external_url or hn_url,
        author=item.get("by"),
        published_at=_parse_unix_time(item.get("time")),
        snippet=snippet,
        raw_ref=str(item_id) if item_id is not None else None,
        raw_hash=_stable_hash(item),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _official_source_items(
    source: OfficialSource,
    raw_text: str,
    *,
    query: str,
    match_mode: str,
) -> tuple[list[ToolEnvelopeItem], ToolError | None]:
    if source.format == "feed":
        return _official_feed_items(source, raw_text, query=query, match_mode=match_mode)
    if source.format == "html_page":
        return _official_html_page_items(source, raw_text, query=query, match_mode=match_mode), None
    return (
        [],
        ToolError(
            code=f"{source.key}_unsupported_format",
            message=f"Unsupported official source format: {source.format}",
            retryable=False,
        ),
    )


def _official_feed_items(
    source: OfficialSource,
    raw_text: str,
    *,
    query: str,
    match_mode: str,
) -> tuple[list[ToolEnvelopeItem], ToolError | None]:
    try:
        root = ElementTree.fromstring(raw_text)
    except ElementTree.ParseError:
        return (
            [],
            ToolError(
                code=f"{source.key}_unexpected_payload",
                message=f"Expected RSS or Atom feed for {source.name}",
                retryable=False,
            ),
        )

    tag = _local_name(root.tag)
    if tag == "feed":
        items = [_official_atom_item(source, entry) for entry in root.findall("atom:entry", XML_NS)]
    elif tag == "rss":
        channel = root.find("channel")
        raw_items = channel.findall("item") if channel is not None else []
        items = [_official_rss_item(source, item) for item in raw_items]
    else:
        return (
            [],
            ToolError(
                code=f"{source.key}_unexpected_payload",
                message=f"Expected RSS or Atom feed for {source.name}",
                retryable=False,
            ),
        )

    return (
        [
            item
            for item in items
            if _matches_query(
                " ".join([item.title, item.snippet, str(item.metadata.get("source_name", ""))]),
                query=query,
                match_mode=match_mode,
            )
        ],
        None,
    )


def _official_atom_item(source: OfficialSource, entry: ElementTree.Element) -> ToolEnvelopeItem:
    title = _normalize_space(_xml_text(entry, "atom:title") or f"{source.name} update")
    snippet = _html_fragment_text(
        _xml_text(entry, "atom:summary")
        or _xml_text(entry, "atom:content")
        or f"Official update from {source.name}."
    )
    url = _xml_text(entry, "atom:id")
    for link in entry.findall("atom:link", XML_NS):
        if link.attrib.get("rel") in {None, "", "alternate"} and link.attrib.get("href"):
            url = link.attrib["href"]
            break
    authors = [
        _normalize_space(_xml_text(author, "atom:name") or "")
        for author in entry.findall("atom:author", XML_NS)
    ]
    authors = [author for author in authors if author]
    published_at = _parse_datetime(_xml_text(entry, "atom:published")) or _parse_datetime(
        _xml_text(entry, "atom:updated")
    )
    raw_payload = {
        "source_key": source.key,
        "title": title,
        "url": url,
        "published": _xml_text(entry, "atom:published"),
        "updated": _xml_text(entry, "atom:updated"),
        "authors": authors,
        "snippet": snippet,
    }
    return ToolEnvelopeItem(
        title=title,
        url=url,
        author=", ".join(authors[:5]) if authors else source.name,
        published_at=published_at,
        snippet=snippet,
        raw_ref=_xml_text(entry, "atom:id") or url,
        raw_hash=_stable_hash(raw_payload),
        metadata={
            "kind": source.feed_item_kind,
            "source_key": source.key,
            "source_name": source.name,
            "source_url": source.url,
            "homepage": source.homepage,
            "feed_format": "atom",
        },
    )


def _official_rss_item(source: OfficialSource, item: ElementTree.Element) -> ToolEnvelopeItem:
    title = _normalize_space(_child_text(item, "title") or f"{source.name} update")
    link = _child_text(item, "link") or source.homepage or source.url
    description = _html_fragment_text(
        _child_text(item, "description")
        or _xml_text(item, "content:encoded")
        or f"Official update from {source.name}."
    )
    guid = _child_text(item, "guid")
    author = _child_text(item, "dc:creator") or _child_text(item, "author") or source.name
    published_at = _parse_rss_datetime(_child_text(item, "pubDate"))
    raw_payload = {
        "source_key": source.key,
        "title": title,
        "link": link,
        "guid": guid,
        "author": author,
        "pubDate": _child_text(item, "pubDate"),
        "description": description,
    }
    return ToolEnvelopeItem(
        title=title,
        url=link,
        author=author,
        published_at=published_at,
        snippet=description,
        raw_ref=guid or link,
        raw_hash=_stable_hash(raw_payload),
        metadata={
            "kind": source.feed_item_kind,
            "source_key": source.key,
            "source_name": source.name,
            "source_url": source.url,
            "homepage": source.homepage,
            "feed_format": "rss",
        },
    )


def _official_html_page_items(
    source: OfficialSource,
    raw_text: str,
    *,
    query: str,
    match_mode: str,
) -> list[ToolEnvelopeItem]:
    extracted = _extract_html_text(raw_text)
    page_title = extracted["title"] or source.name
    sections = extracted["sections"] or [{"heading": page_title, "text": extracted["text"]}]
    items: list[ToolEnvelopeItem] = []
    seen_sections: set[tuple[str, str]] = set()
    for section in sections:
        heading = _normalize_space(section.get("heading") or page_title)
        text = _normalize_space(section.get("text") or "")
        if not text:
            continue
        if _generic_html_heading(heading):
            continue
        if not _matches_query(f"{heading} {text}", query=query, match_mode=match_mode):
            continue
        snippet = text[:1000]
        section_key = (heading.lower(), snippet.lower())
        if section_key in seen_sections:
            continue
        seen_sections.add(section_key)
        raw_payload = {
            "source_key": source.key,
            "page_title": page_title,
            "heading": heading,
            "snippet": snippet,
        }
        items.append(
            ToolEnvelopeItem(
                title=f"{source.name}: {heading}",
                url=source.url,
                author=source.name,
                snippet=snippet,
                raw_ref=f"{source.key}:{heading}",
                raw_hash=_stable_hash(raw_payload),
                metadata={
                    "kind": source.html_item_kind,
                    "source_key": source.key,
                    "source_name": source.name,
                    "source_url": source.url,
                    "homepage": source.homepage,
                    "page_title": page_title,
                    "heading": heading,
                },
            )
        )
    return items


def _github_headers(token: str | None, user_agent: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _huggingface_headers(token: str | None, user_agent: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": user_agent,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": user_agent,
    }


def _public_headers(user_agent: str, *, accept: str) -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": user_agent,
    }


def _selected_source_keys(
    params: dict[str, Any],
    *,
    catalog: dict[str, OfficialSource],
    default_source_keys: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    requested = _source_key_list(params.get("source_keys", params.get("source_key")))
    if not requested:
        requested = list(default_source_keys)

    selected: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for key in requested:
        if key in seen:
            continue
        seen.add(key)
        if key in catalog:
            selected.append(key)
        else:
            unknown.append(key)

    max_sources = _bounded_int(
        params.get("max_sources"),
        default=len(default_source_keys),
        minimum=1,
        maximum=max(len(catalog), 1),
    )
    return selected[:max_sources], unknown


def _source_key_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [str(value)]
    return [item.strip() for item in raw_values if item and item.strip()]


def _match_mode(value: Any) -> str:
    return "all" if str(value).lower() == "all" else "any"


def _matches_query(text: str, *, query: str, match_mode: str) -> bool:
    terms = [term for term in re.findall(r"[a-z0-9][a-z0-9_.+-]*", query.lower()) if len(term) >= 2]
    if not terms:
        return True
    haystack = text.lower()
    if match_mode == "all":
        return all(term in haystack for term in terms)
    return any(term in haystack for term in terms)


def _child_text(element: ElementTree.Element, tag: str) -> str | None:
    found = element.find(tag, XML_NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _parse_rss_datetime(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return _parse_datetime(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_cik(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return digits.zfill(10)


def _sec_ticker_from_context(context: ToolExecutionContext) -> str | None:
    explicit = context.params.get("ticker")
    if explicit:
        return str(explicit).strip().upper().lstrip("$")
    match = re.search(r"\$([A-Za-z][A-Za-z0-9.-]{0,9})\b", context.query)
    if match:
        return match.group(1).upper()
    match = re.match(r"\s*([A-Z][A-Z0-9.-]{0,9})\b", context.query)
    if match:
        return match.group(1).upper()
    return None


def _hacker_news_feed(value: Any) -> str:
    feed = str(value or "new").strip().lower()
    return feed if feed in HACKER_NEWS_FEEDS else "new"


def _parse_unix_time(value: Any):
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _url_domain(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", value, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower()


def _sec_filing_url(cik: str, accession_number: Any, primary_document: Any) -> str | None:
    accession_path = _sec_accession_path(cik, accession_number)
    if accession_path is None:
        return None
    if primary_document:
        return f"{accession_path}/{primary_document}"
    return accession_path


def _sec_accession_url(cik: str, accession_number: Any) -> str | None:
    return _sec_accession_path(cik, accession_number)


def _sec_accession_path(cik: str, accession_number: Any) -> str | None:
    if not accession_number:
        return None
    cik_int = str(int(cik))
    accession_clean = str(accession_number).replace("-", "")
    return f"{SEC_ARCHIVES_BASE_URL}/{cik_int}/{accession_clean}"


def _parse_sec_date(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return _parse_datetime(value)


def _string_list(value: Any, *, default: tuple[str, ...] = ()) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        raw_values = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [str(value)]
    return [item.strip() for item in raw_values if item and item.strip()]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _html_fragment_text(value: str) -> str:
    extracted = _extract_html_text(value)
    return _normalize_space(extracted["text"] or value)


def _generic_html_heading(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "api reference",
        "contents",
        "developers",
        "docs",
        "navigation",
        "on this page",
        "products",
        "resources",
        "suggested",
        "table of contents",
    }


def _extract_html_text(value: str) -> dict[str, Any]:
    parser = _OfficialHtmlParser()
    parser.feed(value)
    return parser.finish()


class _OfficialHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.sections: list[dict[str, str]] = []
        self._ignore_depth = 0
        self._in_title = False
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._current_heading: str | None = None
        self._current_parts: list[str] = []
        self._saw_main = False
        self._main_depth = 0

    def handle_starttag(self, tag: str, attrs):
        normalized = tag.lower()
        if normalized in {"script", "style", "svg", "noscript"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if normalized == "main":
            self._saw_main = True
            self._main_depth += 1
            self.text_parts = []
            self.sections = []
            self._current_parts = []
            self._current_heading = None
            self._heading_tag = None
            self._heading_parts = []
            return
        if normalized == "title":
            self._in_title = True
            return
        if self._saw_main and self._main_depth == 0:
            return
        if normalized in {"h1", "h2", "h3", "h4"}:
            self._finish_section()
            self._heading_tag = normalized
            self._heading_parts = []
            self._current_heading = None

    def handle_endtag(self, tag: str):
        normalized = tag.lower()
        if normalized in {"script", "style", "svg", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if self._ignore_depth:
            return
        if normalized == "main" and self._main_depth:
            self._finish_section()
            self._main_depth -= 1
            return
        if normalized == "title":
            self._in_title = False
            return
        if self._saw_main and self._main_depth == 0:
            return
        if self._heading_tag == normalized:
            heading = _normalize_space(" ".join(self._heading_parts))
            self._current_heading = heading or None
            if heading:
                self.text_parts.append(heading)
            self._heading_tag = None
            self._heading_parts = []

    def handle_data(self, data: str):
        if self._ignore_depth:
            return
        text = _normalize_space(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
            return
        if self._saw_main and self._main_depth == 0:
            return
        if self._heading_tag:
            self._heading_parts.append(text)
            return
        self.text_parts.append(text)
        self._current_parts.append(text)

    def finish(self) -> dict[str, Any]:
        self._finish_section()
        return {
            "title": _normalize_space(" ".join(self.title_parts)),
            "text": _normalize_space(" ".join(self.text_parts)),
            "sections": self.sections,
        }

    def _finish_section(self) -> None:
        section_text = _normalize_space(" ".join(self._current_parts))
        if section_text:
            self.sections.append(
                {
                    "heading": self._current_heading or "Page",
                    "text": section_text,
                }
            )
        self._current_parts = []


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _timeout_seconds(context: ToolExecutionContext) -> int:
    return _bounded_int(context.params.get("timeout_seconds"), default=20, minimum=1, maximum=120)


def _parse_datetime(value: Any):
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _arxiv_search_query(query: str) -> str:
    stripped = query.strip()
    if ":" in stripped:
        return stripped
    return f"all:{stripped}"


def _xml_text(element: ElementTree.Element, path: str) -> str | None:
    found = element.find(path, XML_NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _xml_attr(element: ElementTree.Element, path: str, attr: str) -> str | None:
    found = element.find(path, XML_NS)
    if found is None:
        return None
    return found.attrib.get(attr)


def _arxiv_id(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1]


def _content_value(content: dict[str, Any], key: str) -> Any | None:
    value = content.get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _parse_openreview_time(value: Any):
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _unexpected_payload_envelope(response: ToolEnvelope, *, expected_shape: str) -> ToolEnvelope:
    return response.model_copy(
        update={
            "errors": [
                ToolError(
                    code="unexpected_payload",
                    message=f"Expected source payload shape: {expected_shape}",
                    retryable=False,
                )
            ],
            "metadata": {
                **{
                    key: value
                    for key, value in response.metadata.items()
                    if key not in {"raw_payload", "raw_text"}
                },
                "payload_type": type(
                    response.metadata.get("raw_payload", response.metadata.get("raw_text"))
                ).__name__,
            },
        }
    )
