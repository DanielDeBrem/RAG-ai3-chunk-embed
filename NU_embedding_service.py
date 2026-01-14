from typing import List
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

# ---------- FastAPI App ----------

app = FastAPI(title="AI-3 Embedding Service", version="0.1.0")


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


class HealthResponse(BaseModel):
    status: str
    service: str
    model: str


@app.get("/health", response_model=HealthResponse)
def health():
    model_name = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
    return HealthResponse(
        status="ok",
        service="ai3-embedding",
        model=model_name
    )


@app.post("/embed", response_model=EmbedResponse)
def embed_endpoint(req: EmbedRequest):
    """Embed een lijst van teksten naar vectoren."""
    try:
        if not req.texts:
            raise HTTPException(status_code=400, detail="No texts provided")
        embeddings = embed_texts(req.texts)
        return EmbedResponse(embeddings=embeddings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")


# ---------- Model & Functions ----------

_model = None


def get_model() -> SentenceTransformer:
    """
    Lazy load van de embedder.
    We draaien bewust op CPU omdat de GPU al vol zit met llama3.1:70b via Ollama.
    """
    global _model
    if _model is None:
        model_name = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
        # FORCEER CPU – GPU zit vol met 70B
        device = "cpu"
        _model = SentenceTransformer(model_name, device=device)
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed een lijst van teksten naar een lijst van vectoren (list[list[float]]).
    """
    if isinstance(texts, str):
        texts = [texts]

    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=8,           # klein houden, we draaien op CPU
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings.tolist()
