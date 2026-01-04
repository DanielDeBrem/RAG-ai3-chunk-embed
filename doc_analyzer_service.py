from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from analyzer_schemas import AnalyzeRequest, AnalyzeResponse
from doc_analyzer import analyze_document

app = FastAPI(title="AI-3 Document Analyzer", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai3-doc-analyzer"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    try:
        analysis = analyze_document(
            text=req.document,
            filename=req.filename,
            mime_type=req.mime_type,
        )
        return AnalyzeResponse(analysis=analysis)
    except Exception as e:
        # laat in ieder geval JSON terugkomen
        raise HTTPException(status_code=500, detail=f"analysis_failed: {e}")
