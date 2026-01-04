import os
import io
import glob
import logging
from typing import List, Dict, Any, Optional

import numpy as np
import faiss
import torch
import pandas as pd

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from docx import Document
from pypdf import PdfReader

# Reranker integratie via HTTP (voorkomt dubbel GPU geheugen)
import httpx

# Contextual Embedding enricher
from contextual_enricher import enrich_chunks_batch, check_context_model_available, CONTEXT_ENABLED

logger = logging.getLogger(__name__)

# ----------------- Config -----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(BASE_DIR, "corpus")

EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")

DEFAULT_DOCUMENT_TYPE = "generic"


# ----------------- Pipelines per document_type -----------------

class ChunkingConfig(BaseModel):
    max_chars: int = 800
    # later kun je hier per type extra flags zetten (tabellen, dialogs, etc.)


PIPELINE_CONFIG: Dict[str, ChunkingConfig] = {
    "generic": ChunkingConfig(max_chars=800),
    "google_reviews": ChunkingConfig(max_chars=600),
    "coaching_chat": ChunkingConfig(max_chars=1200),
    "offertes": ChunkingConfig(max_chars=900),
    "jaarrekening": ChunkingConfig(max_chars=900),
    # voeg vrij toe wat je wilt
}


def get_chunking_config(document_type: str) -> ChunkingConfig:
    return PIPELINE_CONFIG.get(document_type, PIPELINE_CONFIG["generic"])


def classify_document_type(
    text: str,
    filename: str | None = None,
    content_type: str | None = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Heuristische / LLM-stub voor document_type.
    Later kun je dit vervangen door een echte classifier.
    """
    fn = (filename or "").lower()
    t = text[:400].lower()
    meta = metadata or {}

    if "jaarrekening" in fn or "jaarrekening" in t:
        return "jaarrekening"
    if "offerte" in fn or "aanbieding" in t:
        return "offertes"
    if "review" in fn or "google" in fn:
        return "google_reviews"
    if "coach" in t or "sessie" in t:
        return "coaching_chat"

    return DEFAULT_DOCUMENT_TYPE


# ----------------- Schemas -----------------

class HealthResponse(BaseModel):
    status: str
    detail: str = ""


class ChunkHit(BaseModel):
    doc_id: str
    chunk_id: str
    text: str
    score: float
    metadata: Dict[str, Any] = {}


class SearchRequest(BaseModel):
    project_id: str
    document_type: str
    question: str
    top_k: int = 5


class SearchResponse(BaseModel):
    chunks: List[ChunkHit]


class IngestTextRequest(BaseModel):
    project_id: str
    document_type: Optional[str] = None  # als None -> classifier gebruiken
    doc_id: str
    text: str
    chunk_strategy: Optional[str] = None  # als None -> default per document_type
    chunk_overlap: int = 0  # aantal chars overlap tussen chunks
    metadata: Dict[str, Any] = {}


class IngestResponse(BaseModel):
    project_id: str
    document_type: str
    doc_id: str
    chunks_added: int


# ----------------- Index Struct -----------------

class ProjectDocTypeIndex:
    def __init__(self, dim: int, project_id: str, document_type: str):
        self.dim = dim
        self.project_id = project_id
        self.document_type = document_type
        self.index = faiss.IndexFlatIP(dim)
        self.chunks: List[ChunkHit] = []


def make_index_key(project_id: str, document_type: str) -> str:
    return f"{project_id}::{document_type}"


# ----------------- Globals -----------------

app = FastAPI(title="AI-3 DataFactory", version="0.5.0")

model: SentenceTransformer | None = None
indices: Dict[str, ProjectDocTypeIndex] = {}

# Reranker config - roept reranker_service aan op :9200
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "20"))  # Haal meer op voor reranking
RERANK_SERVICE_URL = os.getenv("RERANK_SERVICE_URL", "http://localhost:9200")


# ----------------- Helpers: model / index -----------------

def init_model():
    global model
    if model is not None:
        return
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[AI-3] Laad embed-model {EMBED_MODEL_NAME} op {device}")
    model = SentenceTransformer(EMBED_MODEL_NAME, device=device)


def get_or_create_index(project_id: str, document_type: str, dim: int) -> ProjectDocTypeIndex:
    key = make_index_key(project_id, document_type)
    if key in indices:
        idx = indices[key]
        if idx.dim != dim:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Dim mismatch voor index '{key}': "
                    f"bestaand {idx.dim}, nieuw {dim}"
                ),
            )
        return idx
    idx = ProjectDocTypeIndex(dim=dim, project_id=project_id, document_type=document_type)
    indices[key] = idx
    print(f"[AI-3] Nieuwe index '{key}' (dim={dim})")
    return idx


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        raise ValueError("Geen teksten om te embedden")
    init_model()
    emb = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(emb, dtype="float32")


# ----------------- Helpers: chunking -----------------

# Chunk strategy configuratie
CHUNK_STRATEGY_CONFIG = {
    "default": {"max_chars": 800, "overlap": 0},
    "page_plus_table_aware": {"max_chars": 1500, "overlap": 200, "respect_pages": True},
    "semantic_sections": {"max_chars": 1200, "overlap": 150, "split_on_headers": True},
    "conversation_turns": {"max_chars": 600, "overlap": 0, "split_on_turns": True},
    "table_aware": {"max_chars": 1000, "overlap": 100, "preserve_tables": True},
}


def chunk_default(text: str, max_chars: int = 800, overlap: int = 0) -> List[str]:
    """Standaard chunking op paragrafen met optionele overlap."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""
    
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
                # Overlap: neem laatste deel mee naar volgende chunk
                if overlap > 0 and len(buf) > overlap:
                    buf = buf[-overlap:] + "\n\n" + p
                else:
                    buf = p
            else:
                buf = p
    
    if buf:
        chunks.append(buf)
    if not chunks and text.strip():
        chunks = [text.strip()]
    
    return chunks


def chunk_page_aware(text: str, max_chars: int = 1500, overlap: int = 200) -> List[str]:
    """Chunk op pagina grenzen (voor PDF's met [PAGE X] markers)."""
    import re
    
    # Zoek pagina markers
    pages = re.split(r'\[PAGE \d+\]', text)
    pages = [p.strip() for p in pages if p.strip()]
    
    if not pages:
        return chunk_default(text, max_chars, overlap)
    
    chunks: List[str] = []
    for i, page in enumerate(pages):
        page_header = f"[PAGE {i+1}]\n"
        
        # Als pagina te lang is, split verder
        if len(page) > max_chars:
            sub_chunks = chunk_default(page, max_chars - len(page_header), overlap)
            for sc in sub_chunks:
                chunks.append(page_header + sc)
        else:
            chunks.append(page_header + page)
    
    return chunks


def chunk_semantic_sections(text: str, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    """Chunk op headers/secties (Markdown-achtig)."""
    import re
    
    # Split op headers (# ## ### of === ---)
    sections = re.split(r'(?m)^(#{1,3}\s+.+|.+\n[=-]{3,})$', text)
    sections = [s.strip() for s in sections if s.strip()]
    
    if len(sections) <= 1:
        return chunk_default(text, max_chars, overlap)
    
    chunks: List[str] = []
    current_header = ""
    
    for section in sections:
        # Check of dit een header is
        if re.match(r'^#{1,3}\s+', section) or re.match(r'.+\n[=-]{3,}$', section):
            current_header = section + "\n\n"
        else:
            full_section = current_header + section
            if len(full_section) > max_chars:
                sub_chunks = chunk_default(full_section, max_chars, overlap)
                chunks.extend(sub_chunks)
            else:
                chunks.append(full_section)
    
    return chunks if chunks else chunk_default(text, max_chars, overlap)


def chunk_conversation_turns(text: str, max_chars: int = 600, overlap: int = 0) -> List[str]:
    """Chunk per conversatie turn (voor chatlogs, coaching sessies)."""
    import re
    
    # Split op speaker patterns: "User:", "Assistant:", "Client:", etc.
    turns = re.split(r'(?m)^((?:User|Assistant|Client|Therapist|Coach|Coachee|Q|A|Vraag|Antwoord)\s*:)', text, flags=re.IGNORECASE)
    
    if len(turns) <= 1:
        return chunk_default(text, max_chars, overlap)
    
    chunks: List[str] = []
    current_turn = ""
    
    for i, part in enumerate(turns):
        if re.match(r'^(?:User|Assistant|Client|Therapist|Coach|Coachee|Q|A|Vraag|Antwoord)\s*:', part, re.IGNORECASE):
            if current_turn:
                chunks.append(current_turn.strip())
            current_turn = part
        else:
            current_turn += part
    
    if current_turn:
        chunks.append(current_turn.strip())
    
    # Combineer kleine turns
    merged: List[str] = []
    buf = ""
    for c in chunks:
        if len(buf) + len(c) + 2 <= max_chars:
            buf = f"{buf}\n\n{c}" if buf else c
        else:
            if buf:
                merged.append(buf)
            buf = c
    if buf:
        merged.append(buf)
    
    return merged if merged else chunks


def chunk_table_aware(text: str, max_chars: int = 1000, overlap: int = 100) -> List[str]:
    """Chunk met tabel-preservatie (houdt tabellen bij elkaar)."""
    import re
    
    # Detecteer tabel-achtige structuren (| col | col | of tabs)
    lines = text.split('\n')
    chunks: List[str] = []
    current_chunk: List[str] = []
    in_table = False
    table_buffer: List[str] = []
    
    for line in lines:
        is_table_line = bool(re.match(r'^[\|\+\-].*[\|\+\-]$', line.strip()) or 
                            '\t' in line and line.count('\t') >= 2)
        
        if is_table_line:
            if not in_table and current_chunk:
                # Start nieuwe tabel, sla huidige chunk op
                chunk_text_content = '\n'.join(current_chunk)
                if chunk_text_content.strip():
                    chunks.append(chunk_text_content)
                current_chunk = []
            in_table = True
            table_buffer.append(line)
        else:
            if in_table and table_buffer:
                # Einde van tabel, sla op als eigen chunk
                table_text = '\n'.join(table_buffer)
                chunks.append(f"[TABLE]\n{table_text}")
                table_buffer = []
                in_table = False
            
            current_chunk.append(line)
            
            # Check lengte
            if len('\n'.join(current_chunk)) > max_chars:
                chunk_text_content = '\n'.join(current_chunk[:-1])
                if chunk_text_content.strip():
                    chunks.append(chunk_text_content)
                current_chunk = [current_chunk[-1]] if overlap > 0 else []
    
    # Restanten opslaan
    if table_buffer:
        chunks.append(f"[TABLE]\n{'\n'.join(table_buffer)}")
    if current_chunk:
        chunk_text_content = '\n'.join(current_chunk)
        if chunk_text_content.strip():
            chunks.append(chunk_text_content)
    
    return chunks if chunks else chunk_default(text, max_chars, overlap)


def chunk_text_with_strategy(
    text: str, 
    strategy: Optional[str] = None, 
    document_type: Optional[str] = None,
    overlap: int = 0
) -> List[str]:
    """
    Hoofd chunking functie die de juiste strategie kiest.
    
    Args:
        text: Te chunken tekst
        strategy: Expliciete strategie (optioneel)
        document_type: Document type voor fallback strategie
        overlap: Override voor overlap (0 = gebruik default)
    """
    # Bepaal strategie
    if not strategy:
        # Map document_type naar default strategie
        type_to_strategy = {
            "annual_report_pdf": "page_plus_table_aware",
            "jaarrekening": "page_plus_table_aware",
            "offer_doc": "semantic_sections",
            "offertes": "semantic_sections",
            "coaching_doc": "conversation_turns",
            "coaching_chat": "conversation_turns",
            "chatlog": "conversation_turns",
            "review_doc": "default",
            "google_reviews": "default",
        }
        strategy = type_to_strategy.get(document_type, "default")
    
    # Haal config
    config = CHUNK_STRATEGY_CONFIG.get(strategy, CHUNK_STRATEGY_CONFIG["default"])
    max_chars = config.get("max_chars", 800)
    default_overlap = config.get("overlap", 0)
    effective_overlap = overlap if overlap > 0 else default_overlap
    
    # Voer strategie uit
    if strategy == "page_plus_table_aware":
        return chunk_page_aware(text, max_chars, effective_overlap)
    elif strategy == "semantic_sections":
        return chunk_semantic_sections(text, max_chars, effective_overlap)
    elif strategy == "conversation_turns":
        return chunk_conversation_turns(text, max_chars, effective_overlap)
    elif strategy == "table_aware":
        return chunk_table_aware(text, max_chars, effective_overlap)
    else:
        return chunk_default(text, max_chars, effective_overlap)


def chunk_text(text: str, cfg: ChunkingConfig) -> List[str]:
    """Legacy functie voor backward compatibility."""
    return chunk_default(text, cfg.max_chars)


def ingest_text_into_index(
    project_id: str,
    document_type: str,
    doc_id: str,
    raw_text: str,
    chunk_strategy: Optional[str] = None,
    chunk_overlap: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
    enrich_context: bool = True,  # Nieuw: LLM context enrichment
) -> int:
    """
    Ingest tekst in de index met configureerbare chunking en LLM context enrichment.
    
    Args:
        project_id: Project ID
        document_type: Type document
        doc_id: Document ID
        raw_text: Ruwe tekst om te chunken
        chunk_strategy: Chunking strategie (optioneel, anders op basis van document_type)
        chunk_overlap: Overlap tussen chunks in chars (optioneel)
        metadata: Extra metadata
        enrich_context: Of LLM context moet worden toegevoegd (default True)
    """
    if not raw_text.strip():
        return 0

    # Gebruik de nieuwe strategie-gebaseerde chunking
    chunks = chunk_text_with_strategy(
        text=raw_text,
        strategy=chunk_strategy,
        document_type=document_type,
        overlap=chunk_overlap
    )
    
    if not chunks:
        return 0
    
    # === NIEUW: LLM-based Contextual Enrichment ===
    if enrich_context and CONTEXT_ENABLED:
        # Bouw document metadata voor context generatie
        doc_metadata = {
            "filename": (metadata or {}).get("filename", doc_id),
            "document_type": document_type,
            "main_topics": (metadata or {}).get("main_topics", []),
            "main_entities": (metadata or {}).get("main_entities", []),
        }
        
        print(f"[AI-3] Enriching {len(chunks)} chunks with LLM context...")
        enriched_chunks = enrich_chunks_batch(chunks, doc_metadata)
        
        # Embed de verrijkte chunks
        emb = embed_texts(enriched_chunks)
        
        # Bewaar originele tekst in metadata, verrijkte tekst werd geëmbed
        original_chunks = chunks
        chunks = enriched_chunks
    else:
        emb = embed_texts(chunks)
        original_chunks = chunks
    # === EINDE NIEUW ===
    
    dim = emb.shape[1]

    idx = get_or_create_index(project_id, document_type, dim)

    start_idx = len(idx.chunks)
    idx.index.add(emb)

    base_meta = metadata or {}
    base_meta = {
        **base_meta,
        "project_id": project_id,
        "document_type": document_type,
        "chunk_strategy": chunk_strategy or "auto",
        "context_enriched": enrich_context and CONTEXT_ENABLED,
    }

    for i, ch in enumerate(chunks):
        chunk_id = f"{doc_id}#c{start_idx + i:04d}"
        chunk_meta = {**base_meta}
        # Bewaar ook originele tekst als die verschilt
        if enrich_context and CONTEXT_ENABLED and i < len(original_chunks):
            chunk_meta["original_text"] = original_chunks[i]
        
        idx.chunks.append(
            ChunkHit(
                doc_id=doc_id,
                chunk_id=chunk_id,
                text=ch,  # Verrijkte tekst
                score=0.0,
                metadata=chunk_meta,
            )
        )

    strategy_used = chunk_strategy or f"auto({document_type})"
    context_status = "with LLM context" if (enrich_context and CONTEXT_ENABLED) else "no context"
    print(
        f"[AI-3] Ingest project={project_id} type={document_type} strategy={strategy_used} "
        f"doc_id={doc_id} chunks={len(chunks)} ({context_status}) (totaal={len(idx.chunks)})"
    )
    return len(chunks)


# ----------------- Helpers: file parsers -----------------

def extract_text_from_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        txt = page.extract_text() or ""
        pages.append(f"[PAGE {i+1}]\n{txt}")
    return "\n\n".join(pages)


def extract_text_from_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paras)


def extract_text_from_xlsx(data: bytes) -> str:
    bio = io.BytesIO(data)
    xls = pd.ExcelFile(bio)
    parts: List[str] = []
    for sheet in xls.sheet_names:
        df = xls.parse(sheet).astype(str)
        parts.append(f"=== SHEET: {sheet} ===")
        for row in df.values.tolist():
            parts.append("\t".join(row))
    return "\n".join(parts)


def extract_text_from_csv(data: bytes) -> str:
    bio = io.BytesIO(data)
    df = pd.read_csv(bio).astype(str)
    parts: List[str] = []
    for row in df.values.tolist():
        parts.append("\t".join(row))
    return "\n".join(parts)


def extract_text_from_file(filename: str, data: bytes) -> str:
    fn = filename.lower()
    if fn.endswith((".txt", ".md", ".log", ".json")):
        return extract_text_from_txt(data)
    if fn.endswith(".pdf"):
        return extract_text_from_pdf(data)
    if fn.endswith(".docx"):
        return extract_text_from_docx(data)
    if fn.endswith((".xlsx", ".xls")):
        return extract_text_from_xlsx(data)
    if fn.endswith(".csv"):
        return extract_text_from_csv(data)
    return extract_text_from_txt(data)


# ----------------- Startup: optionele corpus -----------------

def load_initial_corpus():
    if not os.path.isdir(CORPUS_DIR):
        return
    txt_files = sorted(glob.glob(os.path.join(CORPUS_DIR, "*.txt")))
    if not txt_files:
        return

    print(f"[AI-3] Initial corpus: {len(txt_files)} .txt bestanden in {CORPUS_DIR}")
    for path in txt_files:
        doc_id = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()

        # voorlopig één default project "default"
        project_id = "default"
        document_type = classify_document_type(raw, filename=doc_id)

        ingest_text_into_index(
            project_id=project_id,
            document_type=document_type,
            doc_id=doc_id,
            raw_text=raw,
            metadata={"source": "corpus_dir"},
        )


# ----------------- Helpers: reranker (via HTTP naar :9200) -----------------

def check_reranker_available() -> bool:
    """Check of reranker service beschikbaar is."""
    if not RERANK_ENABLED:
        return False
    try:
        resp = httpx.get(f"{RERANK_SERVICE_URL}/health", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


def rerank_chunks_via_http(query: str, chunks: List[ChunkHit], top_k: int) -> List[ChunkHit]:
    """
    Rerank chunks via HTTP call naar reranker_service op :9200.
    Retourneert top_k chunks gesorteerd op rerank score.
    """
    if not RERANK_ENABLED:
        return chunks[:top_k]
    
    if not chunks:
        return []
    
    # Bouw request payload
    items_payload = [
        {"id": c.chunk_id, "text": c.text, "metadata": {}}
        for c in chunks
    ]
    
    try:
        resp = httpx.post(
            f"{RERANK_SERVICE_URL}/rerank",
            json={"query": query, "items": items_payload, "top_k": top_k},
            timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[AI-3] Reranker HTTP call failed: {e} - fallback to vector scores")
        return chunks[:top_k]
    
    # Parse response
    reranked_items = data.get("items", [])
    
    # Maak lookup dict van originele chunks
    chunk_lookup = {c.chunk_id: c for c in chunks}
    
    # Bouw result met rerank scores
    result: List[ChunkHit] = []
    for item in reranked_items:
        orig = chunk_lookup.get(item.get("id"))
        if orig:
            result.append(
                ChunkHit(
                    doc_id=orig.doc_id,
                    chunk_id=orig.chunk_id,
                    text=orig.text,
                    score=float(item.get("score", 0.0)),
                    metadata={**orig.metadata, "reranked": True}
                )
            )
    
    return result


# ----------------- FastAPI events -----------------

@app.on_event("startup")
def on_startup():
    print("[AI-3] Startup – model initialiseren...")
    init_model()
    load_initial_corpus()
    # Check reranker service
    if RERANK_ENABLED:
        if check_reranker_available():
            print(f"[AI-3] Reranker service beschikbaar op {RERANK_SERVICE_URL}")
        else:
            print(f"[AI-3] WAARSCHUWING: Reranker service NIET beschikbaar op {RERANK_SERVICE_URL}")
    else:
        print("[AI-3] Reranker is uitgeschakeld via RERANK_ENABLED=false")
    print("[AI-3] Startup klaar.")


# ----------------- Routes -----------------

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", detail="ai-3 datafactory up")


@app.post("/v1/rag/search", response_model=SearchResponse)
def rag_search(req: SearchRequest):
    """
    Search met optionele reranking via HTTP naar reranker_service.
    
    Flow:
    1. FAISS vector search → top RERANK_CANDIDATES (default 20)
    2. HTTP call naar reranker_service:9200 → top_k (default 5)
    3. Return gerankte resultaten
    """
    key = make_index_key(req.project_id, req.document_type)
    if key not in indices:
        raise HTTPException(
            status_code=404,
            detail=f"Index voor project_id='{req.project_id}' document_type='{req.document_type}' niet gevonden",
        )

    idx = indices[key]
    if not idx.chunks:
        raise HTTPException(
            status_code=404,
            detail=f"Index '{key}' heeft nog geen data",
        )

    # Stap 1: FAISS search - haal meer candidates op als reranking aan staat
    q_emb = embed_texts([req.question])
    
    if RERANK_ENABLED:
        # Haal meer candidates op voor reranking
        candidates_k = min(RERANK_CANDIDATES, len(idx.chunks))
    else:
        # Geen reranking, haal direct top_k
        candidates_k = min(max(req.top_k, 1), len(idx.chunks))
    
    scores, idxs = idx.index.search(q_emb, candidates_k)

    # Bouw candidate hits
    candidates: List[ChunkHit] = []
    for score, i in zip(scores[0], idxs[0]):
        base = idx.chunks[int(i)]
        candidates.append(
            ChunkHit(
                doc_id=base.doc_id,
                chunk_id=base.chunk_id,
                text=base.text,
                score=float(score),
                metadata=base.metadata,
            )
        )

    # Stap 2: Rerank via HTTP als enabled
    if RERANK_ENABLED:
        final_hits = rerank_chunks_via_http(req.question, candidates, req.top_k)
        print(f"[AI-3] Search+Rerank: {len(candidates)} candidates → {len(final_hits)} results")
    else:
        final_hits = candidates[:req.top_k]

    return SearchResponse(chunks=final_hits)


@app.post("/v1/rag/ingest/text", response_model=IngestResponse)
def ingest_text_endpoint(req: IngestTextRequest):
    """
    Ingest tekst met configureerbare chunking strategie.
    
    Beschikbare chunk_strategy waarden:
    - "default": Standaard paragraaf-gebaseerde chunking (800 chars)
    - "page_plus_table_aware": Respecteert pagina grenzen en tabellen (PDF's)
    - "semantic_sections": Split op headers/secties
    - "conversation_turns": Split op dialoog turns (chatlogs)
    - "table_aware": Houdt tabellen bij elkaar
    
    Als chunk_strategy niet opgegeven, wordt automatisch gekozen op basis van document_type.
    """
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is verplicht")

    document_type = req.document_type or classify_document_type(
        req.text,
        filename=req.metadata.get("filename") if req.metadata else None,
        metadata=req.metadata,
    )

    n = ingest_text_into_index(
        project_id=req.project_id,
        document_type=document_type,
        doc_id=req.doc_id,
        raw_text=req.text,
        chunk_strategy=req.chunk_strategy,  # ← NIEUW
        chunk_overlap=req.chunk_overlap,    # ← NIEUW
        metadata=req.metadata,
    )
    return IngestResponse(
        project_id=req.project_id,
        document_type=document_type,
        doc_id=req.doc_id,
        chunks_added=n,
    )


@app.post("/v1/rag/ingest/file", response_model=IngestResponse)
async def ingest_file_endpoint(
    project_id: str = Form(...),
    document_type: Optional[str] = Form(None),
    doc_id: Optional[str] = Form(None),
    chunk_strategy: Optional[str] = Form(None),  # ← NIEUW
    chunk_overlap: int = Form(0),                # ← NIEUW
    file: UploadFile = File(...),
):
    """
    Upload en ingest een bestand met configureerbare chunking.
    
    Ondersteunde bestandstypen: PDF, DOCX, XLSX, CSV, TXT, MD
    
    chunk_strategy opties:
    - "default": Standaard chunking
    - "page_plus_table_aware": PDF met pagina grenzen
    - "semantic_sections": Headers/secties
    - "conversation_turns": Chatlogs
    - "table_aware": Tabel-preservatie
    """
    data = await file.read()
    text = extract_text_from_file(file.filename, data)

    meta = {
        "filename": file.filename,
        "content_type": file.content_type,
    }

    effective_type = document_type or classify_document_type(
        text,
        filename=file.filename,
        content_type=file.content_type,
        metadata=meta,
    )
    effective_doc_id = doc_id or file.filename

    n = ingest_text_into_index(
        project_id=project_id,
        document_type=effective_type,
        doc_id=effective_doc_id,
        raw_text=text,
        chunk_strategy=chunk_strategy,  # ← NIEUW
        chunk_overlap=chunk_overlap,    # ← NIEUW
        metadata=meta,
    )
    return IngestResponse(
        project_id=project_id,
        document_type=effective_type,
        doc_id=effective_doc_id,
        chunks_added=n,
    )
