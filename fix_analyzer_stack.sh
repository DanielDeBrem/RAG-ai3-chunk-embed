#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$PROJECT_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"

backup() {
  local f="$1"
  if [ -f "$f" ]; then
    cp "$f" "${f}.bak_${timestamp}"
    echo "Backup: ${f}.bak_${timestamp}"
  fi
}

backup analyzer_schemas.py
backup doc_analyzer.py
backup doc_analyzer_service.py

# ---------------- analyzer_schemas.py ----------------
cat << 'PY' > analyzer_schemas.py
from __future__ import annotations

from typing import List, Dict, Optional

from pydantic import BaseModel, Field


class DocumentAnalysis(BaseModel):
    document_type: str
    mime_type: Optional[str] = None
    language: Optional[str] = None
    page_count: Optional[int] = None

    has_tables: bool = False
    has_images: bool = False

    main_entities: List[str] = Field(default_factory=list)
    main_topics: List[str] = Field(default_factory=list)

    # hoe we verder moeten chunken / embedden
    suggested_chunk_strategy: str
    suggested_embed_model: str

    # extra hints/flags/metadata
    extra: Dict[str, str] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    document: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None


class AnalyzeResponse(BaseModel):
    analysis: DocumentAnalysis


class HealthResponse(BaseModel):
    status: str
    service: str
PY

echo "analyzer_schemas.py geschreven."

# ---------------- doc_analyzer.py ----------------
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

    # inhouds-heuristiek
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
    nl_markers = [" de ", " het ", " een ", "jaarrekening", "offerte", "factuur"]
    en_markers = [" the ", " and ", " invoice", " report", " statement"]

    nl_score = sum(t.count(m) for m in nl_markers)
    en_score = sum(t.count(m) for m in en_markers)

    if nl_score >= en_score and nl_score > 0:
        return "nl"
    if en_score > nl_score and en_score > 0:
        return "en"
    return "unknown"


def _has_tables(text: str) -> bool:
    lines = text.splitlines()
    numeric_lines = 0
    for ln in lines:
        if sum(c.isdigit() for c in ln) >= 4 and ("  " in ln or ";" in ln or "," in ln):
            numeric_lines += 1
    return numeric_lines >= 3


def _has_images(_: str) -> bool:
    # hier alleen text; echte image-detectie komt later bij PDF parsing
    return False


def _extract_main_entities(text: str, max_items: int = 10) -> List[str]:
    candidates: dict[str, int] = {}
    for token in re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", text):
        candidates[token] = candidates.get(token, 0) + 1
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
    # later via config/DB
    if doc_type in ("financial_statement", "annual_report_pdf", "quotation"):
        return "BAAI/bge-m3"
    if doc_type in ("review_dump", "coaching_notes"):
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
        extra={"filename": filename},
    )
PY

echo "doc_analyzer.py geschreven."

# ---------------- doc_analyzer_service.py ----------------
cat << 'PY' > doc_analyzer_service.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analyzer_schemas import AnalyzeRequest, AnalyzeResponse, HealthResponse
from doc_analyzer import analyze_document

app = FastAPI(title="AI-3 Document Analyzer", version="0.1.0")

# CORS openzetten voor nu (kan later strakker)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(status="ok", service="doc_analyzer_root")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="doc_analyzer")


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    analysis = analyze_document(req)
    return AnalyzeResponse(analysis=analysis)
PY

echo "doc_analyzer_service.py geschreven."

echo "KLAAR: analyzer stack opnieuw gezet."
