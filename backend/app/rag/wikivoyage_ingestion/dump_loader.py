"""Wikivoyage dump loader for Phase D full-rebuild ingestion."""

from __future__ import annotations

import bz2
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.parse import quote
from xml.etree import ElementTree as ET


WIKIVOYAGE_BASE_URL = "https://en.wikivoyage.org/wiki/"


@dataclass(slots=True)
class WikivoyageRawPage:
    """Raw page extracted from the Wikivoyage XML dump."""

    page_id: str
    revision_id: str
    title: str
    wiki_text: str
    source_url: str


def iter_wikivoyage_pages(dump_path: str | Path) -> Iterator[WikivoyageRawPage]:
    """Yield main-namespace Wikivoyage pages from an XML or XML.BZ2 dump."""
    with _open_dump(Path(dump_path)) as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if _local_name(elem.tag) != "page":
                continue

            page = _parse_page_element(elem)
            elem.clear()
            if page is not None:
                yield page


def build_wikivoyage_source_url(title: str) -> str:
    """Build a canonical en.wikivoyage.org page URL from a dump title."""
    normalized = title.strip().replace(" ", "_")
    return WIKIVOYAGE_BASE_URL + quote(normalized, safe="/:_()-")


def _open_dump(path: Path) -> BinaryIO:
    """Open a local dump path, supporting ``.xml`` and ``.xml.bz2`` files."""
    if path.suffix == ".bz2":
        return bz2.open(path, "rb")
    return path.open("rb")


def _parse_page_element(elem: ET.Element) -> WikivoyageRawPage | None:
    """Parse a ``<page>`` element into ``WikivoyageRawPage``."""
    title = _direct_child_text(elem, "title")
    page_id = _direct_child_text(elem, "id")
    revision = _direct_child(elem, "revision")
    revision_id = _direct_child_text(revision, "id") if revision is not None else ""
    wiki_text = _direct_child_text(revision, "text") if revision is not None else ""
    redirect = _direct_child(elem, "redirect")

    if not title or not page_id or not revision_id or not wiki_text:
        return None
    if redirect is not None or wiki_text.lstrip().upper().startswith("#REDIRECT"):
        return None
    if ":" in title:
        return None

    return WikivoyageRawPage(
        page_id=page_id,
        revision_id=revision_id,
        title=title,
        wiki_text=wiki_text,
        source_url=build_wikivoyage_source_url(title),
    )


def _direct_child(elem: ET.Element | None, name: str) -> ET.Element | None:
    """Return the direct child with the requested local tag name."""
    if elem is None:
        return None
    for child in elem:
        if _local_name(child.tag) == name:
            return child
    return None


def _direct_child_text(elem: ET.Element | None, name: str) -> str:
    """Return a direct child's text, stripped, or an empty string."""
    child = _direct_child(elem, name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _local_name(tag: str) -> str:
    """Drop XML namespaces from element tags."""
    if "}" not in tag:
        return tag
    return tag.rsplit("}", 1)[-1]
