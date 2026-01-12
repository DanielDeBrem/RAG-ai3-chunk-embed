from __future__ import annotations

import logging
import os
import re
from typing import Dict, Any, Optional

from analyzer_schemas import DocumentAnalysis
from doc_type_classifier import classify_document

# Import LLM70 client voor AI-4 routing
from llm70_client import (
    get_llm70_client,
    LLM70ConnectionError,
    LLM70TimeoutError,
    LLM70ResponseError,
)
from config.ai3_settings import AI4_FALLBACK_TO_HEURISTICS

logger = logging.getLogger(__name__)


def _detect_language(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["de ", "het ", "een ", "jaarrekening", "balans"]):
        return "nl"
    if any(w in lower for w in ["the ", "and ", "of ", "balance sheet", "income statement"]):
        return "en"
    return "unknown"


def _has_tables(text: str) -> bool:
    lines = text.splitlines()
    numeric_lines = 0
    for line in lines[:200]:
        if re.search(r"\d[\d\.\, ]+\d", line):
            numeric_lines += 1
    return numeric_lines >= 5


def _has_images(_text: str) -> bool:
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


def _llm_enrich_heuristic(document: str,
                          filename: Optional[str],
                          mime_type: Optional[str]) -> Dict[str, Any]:
    """
    Fallback heuristic analysis (snelle versie zonder LLM).
    Gebruikt simpele keyword matching voor basic classification.
    """
    logger.info("Using heuristic fallback for document analysis")
    
    lower_text = document[:2000].lower()
    
    # Detect domain
    domain = "general"
    if any(w in lower_text for w in ["jaarrekening", "balans", "winst", "verlies", "activa", "passiva"]):
        domain = "finance"
    elif any(w in lower_text for w in ["offerte", "aanbieding", "prijs", "kosten", "levering"]):
        domain = "sales"
    elif any(w in lower_text for w in ["coaching", "coach", "sessie", "ontwikkeling"]):
        domain = "coaching"
    elif any(w in lower_text for w in ["review", "beoordeling", "sterren", "rating"]):
        domain = "reviews"
    
    # Detect format from filename/mime
    format_hint = "unknown"
    if filename:
        fn_lower = filename.lower()
        if fn_lower.endswith(".pdf"):
            format_hint = "pdf"
        elif fn_lower.endswith(".docx"):
            format_hint = "docx"
        elif fn_lower.endswith(".txt"):
            format_hint = "txt"
        elif fn_lower.endswith((".html", ".htm")):
            format_hint = "html"
    
    # Basic entity extraction (uppercase words, likely names)
    import re
    entities = []
    words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', document[:2000])
    entities = list(set(words))[:5]  # Max 5 unique
    
    # Basic topic extraction (most common meaningful words)
    topics = []
    common_words = re.findall(r'\b\w{5,}\b', lower_text)
    from collections import Counter
    word_counts = Counter(common_words)
    # Filter out common Dutch stop words
    stop_words = {'zoals', 'worden', 'kunnen', 'moeten', 'omdat', 'echter'}
    topics = [w for w, c in word_counts.most_common(10) if w not in stop_words][:5]
    
    return {
        "entities": entities,
        "topics": topics,
        "domain": domain,
        "extra": {
            "format": format_hint,
            "llm_notes": "heuristic_fallback",
        }
    }


def _llm_enrich_local_8b(document: str,
                         filename: Optional[str],
                         mime_type: Optional[str]) -> Dict[str, Any]:
    """
    Local 8B LLM fallback via Ollama (Tier 2).
    Gebruikt bestaande Ollama instances op GPU 2-7.
    """
    import httpx
    import json
    
    logger.info(f"Using local Ollama 8B for document analysis: {filename}")
    
    # Build analysis prompt
    prompt = f"""Analyseer dit document grondig en return een JSON object met:
- document_type: string (annual_report_pdf, offer_doc, chatlog, coaching_doc, review_doc, generic)
- domain: string (finance, sales, coaching, reviews, general)
- main_entities: array van strings (bedrijven, personen, organisaties)
- main_topics: array van strings (kernonderwerpen)
- has_tables: boolean
- format: string (pdf, docx, txt, html)

Document: {filename or 'unknown'}
MIME: {mime_type or 'unknown'}
Content (eerste 2000 chars):
{document[:2000]}

Return ALLEEN het JSON object, geen extra tekst."""

    # Try first Ollama instance (port 11434)
    ollama_url = os.getenv("DOC_ANALYZER_8B_URL", "http://localhost:11434")
    
    try:
        response = httpx.post(
            f"{ollama_url}/api/generate",
            json={
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 500,
                },
            },
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()
        llm_output = data.get("response", "")
        
        # Parse JSON from LLM output
        # LLM kan extra tekst toevoegen, extract JSON
        import re
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            
            return {
                "entities": result.get("main_entities", []),
                "topics": result.get("main_topics", []),
                "domain": result.get("domain", "general"),
                "extra": {
                    "format": result.get("format", "unknown"),
                    "document_type_8b": result.get("document_type", "generic"),
                    "has_tables_8b": result.get("has_tables", False),
                    "llm_notes": "local_8b",
                }
            }
        else:
            raise ValueError("No JSON found in LLM response")
            
    except Exception as e:
        logger.warning(f"Local 8B analysis failed: {e}")
        raise


def _llm_enrich(document: str,
                filename: Optional[str],
                mime_type: Optional[str]) -> Dict[str, Any]:
    """
    3-Tier Hybrid Document Enrichment:
    
    Tier 1: AI-4 LLM70 (beste kwaliteit, 95%)
    Tier 2: Local Ollama 8B (goede kwaliteit, 85%)
    Tier 3: Heuristics (emergency fallback, 40%)
    """
    llm_client = get_llm70_client()
    
    # Tier 1: AI-4 LLM70 (preferred)
    if llm_client.enabled:
        try:
            logger.info(f"[Tier 1] Calling AI-4 LLM70 for document analysis: {filename}")
            result = llm_client.analyze_document(
                document=document,
                filename=filename,
                mime_type=mime_type,
            )
            logger.info(f"[Tier 1] AI-4 LLM70 analysis successful for {filename}")
            return result
            
        except (LLM70ConnectionError, LLM70TimeoutError) as e:
            logger.warning(f"[Tier 1] AI-4 unavailable: {e}, trying Tier 2...")
        except LLM70ResponseError as e:
            logger.error(f"[Tier 1] AI-4 response error: {e}, trying Tier 2...")
        except Exception as e:
            logger.warning(f"[Tier 1] Unexpected AI-4 error: {e}, trying Tier 2...")
    else:
        logger.info("[Tier 1] AI-4 LLM70 is disabled, skipping to Tier 2")
    
    # Tier 2: Local Ollama 8B (good fallback)
    try:
        logger.info(f"[Tier 2] Using local Ollama 8B for: {filename}")
        result = _llm_enrich_local_8b(document, filename, mime_type)
        logger.info(f"[Tier 2] Local 8B analysis successful for {filename}")
        return result
        
    except Exception as e:
        logger.warning(f"[Tier 2] Local 8B failed: {e}, falling back to Tier 3...")
    
    # Tier 3: Heuristics (last resort)
    logger.info(f"[Tier 3] Using heuristic fallback for: {filename}")
    return _llm_enrich_heuristic(document, filename, mime_type)


def _analyze_document_core(document: str,
                           filename: Optional[str] = None,
                           mime_type: Optional[str] = None) -> DocumentAnalysis:
    language = _detect_language(document)
    has_tables = _has_tables(document)
    has_images = _has_images(document)
    domain = _guess_domain(document)

    doc_type = classify_document(document=document,
                                 filename=filename,
                                 mime_type=mime_type)

    base = DocumentAnalysis(
        document_type=doc_type,
        mime_type=mime_type,
        language=language,
        page_count=None,
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
        logger.warning("LLM enrich crashed: %s", e)
        base.extra.setdefault("llm_error", str(e))

    return base


def analyze_document(*args, **kwargs) -> DocumentAnalysis:
    """
    Compat-laag:
    - ondersteunt zowel analyze_document(text=..., ...) als analyze_document(document=..., ...)
    - ondersteunt ook positional eerste arg als tekst
    """
    document: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None

    if args:
        document = args[0]
        if len(args) > 1:
            filename = args[1]
        if len(args) > 2:
            mime_type = args[2]

    if "text" in kwargs and document is None:
        document = kwargs.pop("text")
    if "document" in kwargs and document is None:
        document = kwargs.pop("document")

    if "filename" in kwargs and filename is None:
        filename = kwargs.pop("filename")
    if "mime_type" in kwargs and mime_type is None:
        mime_type = kwargs.pop("mime_type")

    if document is None:
        raise ValueError("analyze_document requires 'document' or 'text' argument")

    return _analyze_document_core(
        document=document,
        filename=filename,
        mime_type=mime_type,
    )
