"""
embedding_service.py - Redirect naar main app

NOTA: Embedding functionaliteit is geïntegreerd in de main DataFactory app (app.py).
Deze aparte service is niet meer nodig sinds de cleanup.

Deze file bestaat alleen voor backwards compatibility met het start script.
De embedding endpoints zijn beschikbaar via app.py op port 9000.

Voor gebruik: 
- POST /ingest op port 9000 doet automatisch embedding
- GET /embedder/status op port 9000 geeft embedder status
- POST /embedder/unload op port 9000 voor unload

DEPRECATION NOTICE:
Dit bestand en de aparte embedding service op port 8000 zijn DEPRECATED.
Gebruik de main DataFactory API op port 9000.
"""

from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Embedding Service (Deprecated)")


@app.get("/health")
def health():
    """
    Health check - maar waarschuwing dat dit deprecated is.
    """
    logger.warning(
        "[embedding_service] DEPRECATED: This separate embedding service is no longer needed. "
        "Embedding functionality is integrated in the main DataFactory app on port 9000."
    )
    return {
        "status": "deprecated",
        "message": "This service is deprecated. Use DataFactory on port 9000 instead.",
        "redirect": "http://localhost:9000"
    }


@app.get("/")
def root():
    """Root endpoint met deprecation bericht."""
    return {
        "service": "embedding_service",
        "status": "deprecated",
        "message": "Embedding functionality has been integrated into DataFactory (port 9000).",
        "alternatives": {
            "ingest": "POST http://localhost:9000/ingest",
            "embedder_status": "GET http://localhost:9000/embedder/status",
            "embedder_unload": "POST http://localhost:9000/embedder/unload"
        },
        "recommendation": "Stop this service and use DataFactory on port 9000 directly."
    }


if __name__ == "__main__":
    import uvicorn
    logger.warning("Starting DEPRECATED embedding_service - please use DataFactory on port 9000 instead")
    uvicorn.run(app, host="0.0.0.0", port=8000)
