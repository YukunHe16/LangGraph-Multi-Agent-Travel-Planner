"""Cleaning and filtering logic for Wikivoyage dump pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .dump_loader import WikivoyageRawPage


_CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)")
_COUNTRY_RE = re.compile(r"\|\s*country\s*=\s*([^\n|]+)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_FILE_RE = re.compile(r"\[\[\s*(?:File|Image)\s*:[^\]]+\]\]", re.IGNORECASE)
_CATEGORY_TAG_RE = re.compile(r"\[\[\s*Category\s*:[^\]]+\]\]", re.IGNORECASE)
_EXTERNAL_LINK_RE = re.compile(r"\[(https?://[^\s\]]+)\s+([^\]]+)\]")
_HEADING_RE = re.compile(r"^=+\s*(.*?)\s*=+$", re.MULTILINE)
_LINK_RE = re.compile(r"\[\[([^|\]]+)\|?([^\]]*)\]\]")
_APOSTROPHE_RE = re.compile(r"'{2,}")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTILINE_RE = re.compile(r"\n{3,}")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")


@dataclass(slots=True)
class CleanedWikivoyagePage:
    """Cleaned page ready for chunking into RAG documents."""

    page_title: str
    page_id: str
    revision_id: str
    source_url: str
    retrieved_at: str
    content: str
    categories: list[str]
    country_hint: str | None


def clean_wikivoyage_page(
    page: WikivoyageRawPage,
    *,
    allowed_countries: list[str],
    category_roots: list[str],
    min_cleaned_chars: int = 80,
    retrieved_at: str | None = None,
) -> CleanedWikivoyagePage | None:
    """Filter a raw page and convert wiki markup into readable plain text."""
    categories = extract_categories(page.wiki_text)
    country_hint = extract_country_hint(page.wiki_text)
    if not is_target_page(
        title=page.title,
        categories=categories,
        country_hint=country_hint,
        allowed_countries=allowed_countries,
        category_roots=category_roots,
    ):
        return None

    content = clean_wikicode(page.wiki_text)
    if len(content) < min_cleaned_chars:
        return None

    return CleanedWikivoyagePage(
        page_title=page.title,
        page_id=page.page_id,
        revision_id=page.revision_id,
        source_url=page.source_url,
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
        content=content,
        categories=categories,
        country_hint=country_hint,
    )


def extract_categories(wiki_text: str) -> list[str]:
    """Extract page categories from raw Wikivoyage wikitext."""
    return [match.strip() for match in _CATEGORY_RE.findall(wiki_text)]


def extract_country_hint(wiki_text: str) -> str | None:
    """Extract the infobox ``country=`` value when present."""
    match = _COUNTRY_RE.search(wiki_text)
    if match is None:
        return None
    return match.group(1).strip()


def is_target_page(
    *,
    title: str,
    categories: list[str],
    country_hint: str | None,
    allowed_countries: list[str],
    category_roots: list[str],
) -> bool:
    """Return whether a page belongs to the configured China/Japan subset."""
    title_lower = title.lower()
    allowed_country_lowers = [country.lower() for country in allowed_countries]
    category_root_lowers = [root.lower() for root in category_roots]
    category_lowers = [category.lower() for category in categories]
    country_hint_lower = country_hint.lower() if country_hint else ""

    if any(title_lower == country for country in allowed_country_lowers):
        return True
    if any(root in title_lower for root in allowed_country_lowers):
        return True
    if any(root in country_hint_lower for root in allowed_country_lowers):
        return True

    for category in category_lowers:
        if any(root in category for root in category_root_lowers):
            return True
        if any(country in category for country in allowed_country_lowers):
            return True

    return False


def clean_wikicode(wiki_text: str) -> str:
    """Convert common Wikivoyage markup to plain text."""
    text = wiki_text
    text = _COMMENT_RE.sub(" ", text)
    text = _REF_RE.sub(" ", text)
    text = _FILE_RE.sub(" ", text)
    text = _CATEGORY_TAG_RE.sub(" ", text)
    text = _strip_templates(text)
    text = _EXTERNAL_LINK_RE.sub(r"\2", text)
    text = _HEADING_RE.sub(r"\1", text)
    text = _LINK_RE.sub(_replace_link, text)
    text = _APOSTROPHE_RE.sub("", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTILINE_RE.sub("\n\n", text)
    return text.strip()


def _strip_templates(text: str) -> str:
    """Remove template blocks with a small fixed-point loop."""
    previous = text
    for _ in range(8):
        current = _TEMPLATE_RE.sub(" ", previous)
        if current == previous:
            return current
        previous = current
    return previous


def _replace_link(match: re.Match[str]) -> str:
    """Render wiki links using display text when available."""
    target = match.group(1).strip()
    label = match.group(2).strip()
    return label or target
