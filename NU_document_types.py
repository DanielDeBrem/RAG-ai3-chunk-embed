from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DocTypeConfig:
    name: str
    description: str
    chunk_size: int
    overlap: int
    embed_model: str
    rerank_model: str | None = None
    default_labels: List[str] = field(default_factory=list)


DOCUMENT_TYPE_CONFIGS: Dict[str, DocTypeConfig] = {
    "annual_report": DocTypeConfig(
        name="annual_report",
        description="Jaarrekening / financial report (PDF, veel tabellen, vaste structuur).",
        chunk_size=512,
        overlap=64,
        embed_model="BAAI/bge-m3",
        rerank_model="BAAI/bge-reranker-v2-m3",
        default_labels=["finance", "jaarrekening", "tables"],
    ),
    "offer": DocTypeConfig(
        name="offer",
        description="Offerte / proposal aan klanten.",
        chunk_size=384,
        overlap=48,
        embed_model="BAAI/bge-m3",
        rerank_model="BAAI/bge-reranker-v2-m3",
        default_labels=["offerte", "sales"],
    ),
    "menu": DocTypeConfig(
        name="menu",
        description="Menukaart / gerechten voor horeca.",
        chunk_size=256,
        overlap=32,
        embed_model="BAAI/bge-m3",
        rerank_model=None,
        default_labels=["menu", "horeca"],
    ),
    "google_review": DocTypeConfig(
        name="google_review",
        description="Klantreviews (Google Reviews, etc.).",
        chunk_size=256,
        overlap=32,
        embed_model="BAAI/bge-m3",
        rerank_model=None,
        default_labels=["review", "sentiment"],
    ),
    "coaching_chat": DocTypeConfig(
        name="coaching_chat",
        description="Chatlogs van coaching / begeleiding.",
        chunk_size=512,
        overlap=64,
        embed_model="BAAI/bge-m3",
        rerank_model=None,
        default_labels=["chatlog", "coaching"],
    ),
    "spreadsheet_kpi": DocTypeConfig(
        name="spreadsheet_kpi",
        description="Excel/CSV met KPI’s / tabellen.",
        chunk_size=256,
        overlap=32,
        embed_model="BAAI/bge-m3",
        rerank_model="BAAI/bge-reranker-v2-m3",
        default_labels=["spreadsheet", "kpi", "tables"],
    ),
    "generic_text": DocTypeConfig(
        name="generic_text",
        description="Generieke tekst (fallback).",
        chunk_size=512,
        overlap=64,
        embed_model="BAAI/bge-m3",
        rerank_model=None,
        default_labels=["generic"],
    ),
}


def get_config(document_type: str) -> DocTypeConfig:
    # Fallback naar generic_text als type onbekend is
    return DOCUMENT_TYPE_CONFIGS.get(document_type, DOCUMENT_TYPE_CONFIGS["generic_text"])
