from typing import List
import os

from sentence_transformers import SentenceTransformer

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
