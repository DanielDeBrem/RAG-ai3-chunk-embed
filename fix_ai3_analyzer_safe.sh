#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$ROOT"

BACKUP_DIR="$ROOT/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

for f in doc_analyzer.py doc_analyzer_service.py; do
  if [ -f "$f" ]; then
    cp "$f" "$BACKUP_DIR/$f"
  fi
done

echo "Backup in $BACKUP_DIR"

########################
# doc_analyzer.py
########################
cat > doc_analyzer.py << 'PY'
from __future__ import annotations

import logging
import os
import re
from typing import Dict, Any, Optional

import requests

from analyzer_schemas import DocumentAnalysis
from doc_type_classifier import classify_document

logger = logging.getLogger(__name__)

# Llama op AI-3 (ollama)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:70b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))


def _detect_language(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["de ", "het ", "een ", "jaarrekening", "balans"]):
        return "nl"
    if any(w in lower for w in ["the ", "and ", "of ", "balance sheet", "income statement"]):
        return "en"
    return "unknown"


def _has_tables(text: str) -> bool:
    # simpele check op veel cijfers / kolommen
    lines = text.splitlines()
    numeric_lines = 0
    for line in lines[:200]:
        if re.search(r"\d[\d\.\, ]+\d", line):
            numeric_lines += 1
    return numeric_lines >= 5


def _has_images(_text: str) -> bool:
    # zonder echte PDF-parser houden we dit simpel
    return False


def _guess_domain(text: str) -> str:
    lower = text.lower()
    if "jaarrekening" in lower or "balans" in lower or "winst- en verliesrekening" in lower:
        return "finance"
    if "offerte" in lower or "aanbieding" in lower:
        return "sales"
    if "coaching" in lower or "coachingsgesprek" in lower:
        return "coaching"
    if "review" in lower or "beoordeling" in lower or "ster" in lower:
        return "reviews"
    return "general"


def _default_chunk_strategy(doc_type: str, has_tables: bool) -> str:
    if doc_type == "annual_report_pdf":
        return "page_plus_table_aware"
    if doc_type == "offer_doc":
        return "semantic_sections"
    if doc_type == "chatlog":
        return "conversation_turns"
    if has_tables:
        return "table_aware"
    return "default"


def _llm_enrich(document: str,
                filename: Optional[str],
                mime_type: Optional[str]) -> Dict[str, Any]:
    """
    Optionele verrijking via Llama3.1:70b op AI-3.
    Als dit faalt: gewoon lege dict terug, géén exception.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Je bent een document-analyzer. "
                    "Geef een korte JSON met:\n"
                    "- domain: kort domeinwoord (bv. finance, sales, coaching, reviews, general)\n"
                    "- format_hint: bv. pdf, docx, txt, html\n"
                    "- entities: lijst van max 5 belangrijke entiteiten (namen/organisaties)\n"
                    "- topics: lijst van max 5 onderwerpen\n"
                    "Gebruik Nederlands in keys en waarden waar logisch, maar keys zelf Engelstalig laten."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Bestandsnaam: {filename or 'onbekend'}\n"
                    f"MIME type: {mime_type or 'onbekend'}\n\n"
                    f"CONTENT BEGIN:\n{document[:8000]}\nCONTENT EINDE\n\n"
                    "Antwoord ALLEEN met JSON, geen uitleg."
                ),
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
        resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return {"extra": {"llm_error": str(e)}}

    # heel simpele JSON-extractie: probeer direct te parsen, anders regex
    import json

    raw = content.strip()
    json_str = raw
    if not raw.startswith("{"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            json_str = m.group(0)

    try:
        parsed = json.loads(json_str)
    except Exception as e:
        logger.warning("LLM JSON parse failed: %s ; raw=%r", e, raw[:300])
        return {"extra": {"llm_raw": raw[:500]}}

    result: Dict[str, Any] = {}
    domain = parsed.get("domain") or parsed.get("domein")
    format_hint = parsed.get("format_hint") or parsed.get("formaat")
    entities = parsed.get("entities") or parsed.get("entiteiten") or []
    topics = parsed.get("topics") or parsed.get("onderwerpen") or []

    extra: Dict[str, Any] = {}
    if format_hint:
        extra["format"] = format_hint
    extra["llm_notes"] = "parsed_by_llama3_70b"

    result["entities"] = entities
    result["topics"] = topics
    result["domain"] = domain
    result["extra"] = extra
    return result


def analyze_document(document: str,
                     filename: Optional[str] = None,
                     mime_type: Optional[str] = None) -> DocumentAnalysis:
    """
    Centrale analyzer:
    - heuristieken
    - doc_type_classifier
    - optionele LLM-verrijking
    """
    # 1) basis heuristiek
    language = _detect_language(document)
    has_tables = _has_tables(document)
    has_images = _has_images(document)
    domain = _guess_domain(document)

    # 2) simpele type-classifier (heuristiek)
    doc_type = classify_document(document=document,
                                 filename=filename,
                                 mime_type=mime_type)

    # 3) default chunk-strategy + embed-model
    base = DocumentAnalysis(
        document_type=doc_type,
        mime_type=mime_type,
        language=language,
        page_count=None,  # zonder echte PDF-parser moeilijk
        has_tables=has_tables,
        has_images=has_images,
        main_entities=[],
        main_topics=[],
        suggested_chunk_strategy=_default_chunk_strategy(doc_type, has_tables),
        suggested_embed_model="BAAI/bge-m3",
        extra={},
    )

    base.extra["filename"] = filename or ""
    base.extra["domain"] = domain
    if mime_type:
        base.extra["mime_hint"] = mime_type

    # 4) optionele LLM-verrijking
    try:
        llm_info = _llm_enrich(document, filename, mime_type)
        if llm_info:
            ents = llm_info.get("entities") or []
            topics = llm_info.get("topics") or []
            if ents:
                base.main_entities = ents
            if topics:
                base.main_topics = topics
            dom2 = llm_info.get("domain")
            if dom2:
                base.extra["domain_llm"] = dom2
            extra = llm_info.get("extra") or {}
            base.extra.update(extra)
    except Exception as e:
        # NOOIT laten crashen
        logger.warning("LLM enrich crashed: %s", e)
        base.extra.setdefault("llm_error", str(e))

    return base
PY

########################
# doc_analyzer_service.py
########################
cat > doc_analyzer_service.py << 'PY'
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analyzer_schemas import AnalyzeRequest, AnalyzeResponse, DocumentAnalysis
from doc_analyzer import analyze_document

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Doc Analyzer (AI-3)", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "doc_analyzer"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    NOOIT 500 teruggooien. Altijd een AnalyzeResponse.
    Bij fouten komt er info in analysis.extra['error'] of ['llm_error'].
    """
    try:
        analysis = analyze_document(
            document=req.document,
            filename=req.filename,
            mime_type=req.mime_type,
        )
        if isinstance(analysis, dict):
            analysis = DocumentAnalysis(**analysis)
        return AnalyzeResponse(analysis=analysis)
    except Exception as e:
        logger.exception("analyze crashed: %s", e)
        fallback = DocumentAnalysis(
            document_type="unknown",
            mime_type=req.mime_type,
            language="unknown",
            page_count=None,
            has_tables=False,
            has_images=False,
            main_entities=[],
            main_topics=[],
            suggested_chunk_strategy="default",
            suggested_embed_model="BAAI/bge-m3",
            extra={
                "error": str(e),
                "note": "fallback_document_analysis",
            },
        )
        return AnalyzeResponse(analysis=fallback)
PY

echo "Nieuwe analyzer-files geschreven."
