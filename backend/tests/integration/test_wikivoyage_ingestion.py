"""Integration tests for Phase D1 Wikivoyage dump ingestion."""

from __future__ import annotations

import bz2
from pathlib import Path

from app.config.settings import Settings
from app.rag.wikivoyage_ingestion import (
    build_wikivoyage_ingestion_bundle,
    export_payloads_jsonl,
)
from app.rag.wikivoyage_ingestion.chunk_exporter import split_text_into_chunks
from app.rag.wikivoyage_ingestion.dump_loader import build_wikivoyage_source_url


_SAMPLE_DUMP = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Beijing</title>
    <ns>0</ns>
    <id>101</id>
    <revision>
      <id>5001</id>
      <text xml:space="preserve">{{pagebanner|Banner.jpg}}
[[Category:Cities in China]]
| country = China
'''Beijing''' is the capital of China. [[Forbidden City]] is a must-see attraction.
Visitors can also explore [[Temple of Heaven]] and local hutongs.

==See==
* The Forbidden City has imperial architecture and museums.
* Temple of Heaven offers large park grounds and cultural history.
</text>
    </revision>
  </page>
  <page>
    <title>Tokyo</title>
    <ns>0</ns>
    <id>202</id>
    <revision>
      <id>6002</id>
      <text xml:space="preserve">[[Category:Cities in Japan]]
| country = Japan
'''Tokyo''' offers neighborhoods like [[Asakusa]] and [[Shinjuku]].
Travelers often visit Senso-ji, Meiji Shrine, and food markets for a full-day itinerary.</text>
    </revision>
  </page>
  <page>
    <title>London</title>
    <ns>0</ns>
    <id>303</id>
    <revision>
      <id>7003</id>
      <text xml:space="preserve">[[Category:Cities in Europe]]
'''London''' is outside the configured target countries and should be filtered out.</text>
    </revision>
  </page>
  <page>
    <title>Category:China</title>
    <ns>14</ns>
    <id>404</id>
    <revision>
      <id>8004</id>
      <text xml:space="preserve">Administrative category page.</text>
    </revision>
  </page>
</mediawiki>
"""


def _write_dump(path: Path) -> Path:
    path.write_bytes(bz2.compress(_SAMPLE_DUMP.encode("utf-8")))
    return path


def _build_settings() -> Settings:
    settings = Settings()
    settings.rag.enabled = True
    settings.rag.allowed_countries = ["China", "Japan"]
    settings.rag.index_name = "wikivoyage_cn_jp_attractions"
    settings.rag.wikivoyage.min_cleaned_chars = 40
    settings.rag.wikivoyage.chunk_size_chars = 120
    settings.rag.wikivoyage.chunk_overlap_chars = 20
    return settings


class TestWikivoyageIngestion:
    """End-to-end coverage for dump loading, cleaning, and chunk export."""

    def test_ingestion_filters_to_china_and_japan(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage-sample.xml.bz2")

        bundle = build_wikivoyage_ingestion_bundle(dump_path, settings=_build_settings())

        page_titles = [page.page_title for page in bundle["pages"]]
        assert page_titles == ["Beijing", "Tokyo"]
        assert all("London" != title for title in page_titles)

    def test_documents_preserve_required_metadata(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage-sample.xml.bz2")

        bundle = build_wikivoyage_ingestion_bundle(dump_path, settings=_build_settings())

        documents = bundle["documents"]
        assert documents
        for doc in documents:
            assert doc.page_title
            assert doc.page_id
            assert doc.revision_id
            assert doc.source_url.startswith("https://en.wikivoyage.org/wiki/")
            assert doc.retrieved_at is not None
            assert len(doc.content) >= 40

    def test_payloads_are_ready_for_ingest(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage-sample.xml.bz2")

        bundle = build_wikivoyage_ingestion_bundle(dump_path, settings=_build_settings())
        payloads = bundle["payloads"]

        assert payloads
        assert all(payload["index_name"] == "wikivoyage_cn_jp_attractions" for payload in payloads)
        assert all("metadata" in payload for payload in payloads)
        assert all(payload["metadata"]["source_url"].startswith("https://en.wikivoyage.org/wiki/") for payload in payloads)

    def test_export_jsonl_writes_payloads(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage-sample.xml.bz2")
        bundle = build_wikivoyage_ingestion_bundle(dump_path, settings=_build_settings())

        output_path = export_payloads_jsonl(bundle["payloads"], tmp_path / "wikivoyage.jsonl")

        lines = output_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == len(bundle["payloads"])
        assert "wikivoyage_cn_jp_attractions" in lines[0]


class TestChunkingHelpers:
    """Coverage for deterministic chunk behavior used by the ingestion pipeline."""

    def test_split_text_with_overlap(self) -> None:
        text = (
            "Sentence one about Beijing. Sentence two about history. "
            "Sentence three about architecture. Sentence four about food."
        )
        chunks = split_text_into_chunks(text, chunk_size_chars=60, chunk_overlap_chars=10)
        assert len(chunks) >= 2
        assert "Beijing" in chunks[0]

    def test_source_url_uses_wikivoyage_title_encoding(self) -> None:
        url = build_wikivoyage_source_url("Beijing/Chaoyang")
        assert url == "https://en.wikivoyage.org/wiki/Beijing/Chaoyang"
