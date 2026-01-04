#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$PROJECT_DIR"

echo "[AI-3] Working in: $PROJECT_DIR"

# Backup map
BACKUP_DIR="$PROJECT_DIR/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Bestanden die we aanpassen
for f in app.py requirements.txt; do
  if [ -f "$f" ]; then
    echo "[AI-3] Backup $f -> $BACKUP_DIR/$f.bak"
    cp "$f" "$BACKUP_DIR/$f.bak"
  fi
done

echo "[AI-3] Schrijf requirements.txt opnieuw..."
cat <<'EOF' > requirements.txt
fastapi
uvicorn[standard]
sentence-transformers
faiss-cpu
pydantic
numpy
torch
pandas
python-docx
openpyxl
pypdf
EOF

echo "[AI-3] Schrijf app.py opnieuw..."
cat <<'EOF' > app.py
import os
import io
import glob
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

app = FastAPI(title="AI-3 DataFactory", version="0.4.0")

model: SentenceTransformer | None = None
indices: Dict[str, ProjectDocTypeIndex] = {}


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

def chunk_text(text: str, cfg: ChunkingConfig) -> List[str]:
    max_chars = cfg.max_chars
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    if not chunks and text.strip():
        chunks = [text.strip()]
    return chunks


def ingest_text_into_index(
    project_id: str,
    document_type: str,
    doc_id: str,
    raw_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    if not raw_text.strip():
        return 0

    cfg = get_chunking_config(document_type)
    chunks = chunk_text(raw_text, cfg)
    emb = embed_texts(chunks)
    dim = emb.shape[1]

    idx = get_or_create_index(project_id, document_type, dim)

    start_idx = len(idx.chunks)
    idx.index.add(emb)

    base_meta = metadata or {}
    base_meta = {
        **base_meta,
        "project_id": project_id,
        "document_type": document_type,
    }

    for i, ch in enumerate(chunks):
        chunk_id = f"{doc_id}#c{start_idx + i:04d}"
        idx.chunks.append(
            ChunkHit(
                doc_id=doc_id,
                chunk_id=chunk_id,
                text=ch,
                score=0.0,
                metadata=base_meta,
            )
        )

    print(
        f"[AI-3] Ingest project={project_id} type={document_type} "
        f"doc_id={doc_id} chunks={len(chunks)} (totaal={len(idx.chunks)})"
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


# ----------------- FastAPI events -----------------

@app.on_event("startup")
def on_startup():
    print("[AI-3] Startup – model initialiseren...")
    init_model()
    load_initial_corpus()
    print("[AI-3] Startup klaar.")


# ----------------- Routes -----------------

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", detail="ai-3 datafactory up")


@app.post("/v1/rag/search", response_model=SearchResponse)
def rag_search(req: SearchRequest):
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

    q_emb = embed_texts([req.question])
    k = min(max(req.top_k, 1), len(idx.chunks))
    scores, idxs = idx.index.search(q_emb, k)

    hits: List[ChunkHit] = []
    for score, i in zip(scores[0], idxs[0]):
        base = idx.chunks[int(i)]
        hits.append(
            ChunkHit(
                doc_id=base.doc_id,
                chunk_id=base.chunk_id,
                text=base.text,
                score=float(score),
                metadata=base.metadata,
            )
        )

    return SearchResponse(chunks=hits)


@app.post("/v1/rag/ingest/text", response_model=IngestResponse)
def ingest_text_endpoint(req: IngestTextRequest):
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
    file: UploadFile = File(...),
):
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
        metadata=meta,
    )
    return IngestResponse(
        project_id=project_id,
        document_type=effective_type,
        doc_id=effective_doc_id,
        chunks_added=n,
    )
EOF

echo "[AI-3] Zorg voor venv + dependencies..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo
echo "[AI-3] Klaar. Start de service met bijvoorbeeld:"
echo "  cd \"$PROJECT_DIR\""
echo "  source .venv/bin/activate"
echo "  uvicorn app:app --host 0.0.0.0 --port 9000"
