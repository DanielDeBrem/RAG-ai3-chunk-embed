from __future__ import annotations

import json
from typing import Optional, Dict, Any

import httpx

# We draaien alles lokaal op AI-3
OLLAMA_BASE_URL = "http://localhost:11434"
LLM_PLANNER_MODEL = "llama3.1:70b"

SYSTEM_PROMPT = """
You are a high-end document analyst and chunking planner for a RAG system.

Your job:
- Do deep analysis of the uploaded document preview.
- Detect language, domain, and format.
- Extract key entities and important relations between them.
- Understand the context and purpose of the document.
- Propose the best possible chunking strategy for later embedding/search.
- Suggest the best embedding model (we currently mostly use BAAI/bge-m3).

You MUST respond with a single valid JSON object like:

{
  "language": "nl",
  "domain": "finance/annual_report",
  "format": "structured_pdf_with_tables",

  "entities": [
    "DaSol B.V.",
    "boekjaar 2017",
    "balans per 31 december 2017"
  ],

  "relations": [
    "DaSol B.V. - heeft jaarrekening over boekjaar 2017",
    "Jaarrekening 2017 - bevat balans per 31 december 2017"
  ],

  "topics": [
    "finance",
    "accounting",
    "dutch_annual_report"
  ],

  "has_tables": true,
  "has_images": false,

  "chunk_strategy": "page_plus_table_aware",

  "recommended_embed_model": "BAAI/bge-m3",

  "notes": "Short explanation why this chunk strategy and embed model fit this document."
}

Rules:
- ALWAYS output valid JSON.
- Do NOT add markdown, comments or extra text.
- If you are unsure about something, make a best effort guess and still fill the fields.
"""


def enrich_with_llm(
    preview_text: str,
    filename: Optional[str],
    mime_type: Optional[str],
    heuristics: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Roept lokaal llama3.1:70b via Ollama aan om:
    - language/domain/format
    - entities/relations/topics
    - chunk_strategy
    - recommended_embed_model
    te laten bepalen.
    """

    # Beperk de preview zodat we niet idioot veel sturen
    short_preview = preview_text[:4000]

    user_prompt = f"""
Document filename: {filename or "unknown"}
MIME type: {mime_type or "unknown"}

Heuristic document_type: {heuristics.get("document_type")}
Heuristic language_guess: {heuristics.get("language")}

Here is the document preview (first characters):

\"\"\"{short_preview}\"\"\"

Analyse this preview and return the JSON object as described in the system prompt.
"""

    payload = {
        "model": LLM_PLANNER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[meta_enricher] Ollama call failed: {e}")
        return None

    try:
        data = resp.json()
    except Exception as e:
        print(f"[meta_enricher] invalid JSON from Ollama HTTP response: {e}")
        return None

    content = (
        data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
    )
    content = content.strip()

    if not content:
        print("[meta_enricher] empty content from LLM")
        return None

    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        print("[meta_enricher] LLM output is not valid JSON, got:", content[:200])
        return None

    if not isinstance(obj, dict):
        print("[meta_enricher] LLM JSON is not an object:", type(obj))
        return None

    return obj
