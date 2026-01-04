#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$PROJECT_DIR"

BACKUP="doc_analyzer.py.bak_$(date +%Y%m%d_%H%M%S)"
if [ -f doc_analyzer.py ]; then
    cp doc_analyzer.py "$BACKUP"
    echo "Backup gemaakt: $BACKUP"
fi

cat << 'PY' > doc_analyzer.py
from __future__ import annotations

import re
from typing import List

from analyzer_schemas import AnalyzeRequest, DocumentAnalysis


def _guess_document_type(text: str, filename: str | None) -> str:
    lname = (filename or "").lower()

    # op extensie gokken
    if lname.endswith(".pdf"):
        return "annual_report_pdf"
    if lname.endswith(".doc") or lname.endswith(".docx"):
        return "office_doc"
    if lname.endswith(".xls") or lname.endswith(".xlsx"):
        return "spreadsheet"
    if lname.endswith(".txt"):
        return "plain_text"

    # op inhoud gokken
    t = text.lower()
    if "jaarrekening" in t or "balans" in t or "winst-en-verliesrekening" in t:
        return "financial_statement"
    if "offerte" in t or "aanbieding" in t:
        return "quotation"
    if "google review" in t or "google reviews" in t:
        return "review_dump"
    if "coach" in t or "coachee" in t or "sessie" in t:
        return "coaching_notes"

    return "generic_text"


def _detect_language(text: str) -> str:
    t = text.lower()
    # ultra cheap heuristiek
    nl_markers = ["de ", "het ", "een ", "jaarrekening", "offerte", "factuur"]
    en_markers = ["the ", "and ", "invoice", "report", "statement"]

    nl_score = sum(t.count(m) for m in nl_markers)
    en_score = sum(t.count(m) for m in en_markers)

    if nl_score >= en_score and nl_score > 0:
        return "nl"
    if en_score > nl_score and en_score > 0:
        return "en"
    return "unknown"


def _has_tables(text: str) -> bool:
    # simpele hint: veel cijfers + kolom-achtige spacing
    lines = text.splitlines()
    numeric_lines = 0
    for ln in lines:
        if sum(c.isdigit() for c in ln) >= 4 and ("  " in ln or ";" in ln or "," in ln):
            numeric_lines += 1
    return numeric_lines >= 3


def _has_images(_: str) -> bool:
    # we zien hier alleen text; echte detectie doen we later op pagina-niveau / via pdf parser
    return False


def _extract_main_entities(text: str, max_items: int = 10) -> List[str]:
    # ultradomme entity-guess: woorden met hoofdletter in midden van zin
    candidates: dict[str, int] = {}
    for token in re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", text):
        candidates[token] = candidates.get(token, 0) + 1
    # sorteer op frequency
    sorted_items = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_items[:max_items]]


def _extract_main_topics(text: str, max_items: int = 5) -> List[str]:
    t = text.lower()
    topics: list[str] = []
    if any(k in t for k in ["jaarrekening", "balans", "winst-en-verliesrekening"]):
        topics.append("finance")
    if any(k in t for k in ["review", "beoordeling", "ervaring"]):
        topics.append("reviews")
    if any(k in t for k in ["offerte", "aanbieding", "prijs", "tarief"]):
        topics.append("offers")
    if any(k in t for k in ["coach", "coachee", "sessie", "begeleiding"]):
        topics.append("coaching")
    if not topics:
        topics.append("general")
    return topics[:max_items]


def _choose_chunk_strategy(doc_type: str, has_tables: bool) -> str:
    # hier coderen we de "agentic" keuze-heuristiek
    if doc_type in ("financial_statement", "annual_report_pdf"):
        return "page_plus_table_aware"
    if doc_type == "quotation":
        return "semantic_paragraphs"
    if doc_type == "review_dump":
        return "per_review"
    if doc_type == "spreadsheet":
        return "sheet_row_blocks"
    if has_tables:
        return "table_plus_paragraphs"
    return "semantic_paragraphs"


def _choose_embed_model(doc_type: str) -> str:
    # later kun je dit via config of DB doen
    if doc_type in ("financial_statement", "annual_report_pdf", "quotation"):
        return "BAAI/bge-m3"
    if doc_type == "review_dump":
        return "BAAI/bge-m3"
    if doc_type == "coaching_notes":
        return "BAAI/bge-m3"
    return "BAAI/bge-m3"


def analyze_document(req: AnalyzeRequest) -> DocumentAnalysis:
    text = req.document or ""
    filename = req.filename or ""
    mime_type = req.mime_type

    document_type = _guess_document_type(text, filename)
    language = _detect_language(text)
    has_tables = _has_tables(text)
    has_images = _has_images(text)
    main_entities = _extract_main_entities(text)
    main_topics = _extract_main_topics(text)

    # page_count kennen we hier nog niet; dat doen we pas bij PDF parsing
    suggested_chunk_strategy = _choose_chunk_strategy(document_type, has_tables)
    suggested_embed_model = _choose_embed_model(document_type)

    return DocumentAnalysis(
        document_type=document_type,
        mime_type=mime_type,
        language=language,
        page_count=None,
        has_tables=has_tables,
        has_images=has_images,
        main_entities=main_entities,
        main_topics=main_topics,
        suggested_chunk_strategy=suggested_chunk_strategy,
        suggested_embed_model=suggested_embed_model,
        extra={
            "filename": filename,
        },
    )
PY

echo "doc_analyzer.py opnieuw geschreven."
