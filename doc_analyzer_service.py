from __future__ import annotations

import logging
import uuid
import threading
from datetime import datetime
from typing import Dict, Optional, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analyzer_schemas import AnalyzeRequest, AnalyzeResponse, DocumentAnalysis
from doc_analyzer import analyze_document

# Parallel analyzer voor grote documenten
from parallel_analyzer import (
    should_use_parallel_analysis,
    parallel_analyze_document,
)

# GPU manager voor status endpoint
from gpu_manager import gpu_manager

# Status reporter voor webhooks naar AI-4
from status_reporter import (
    report_received, report_analyzing, report_completed, report_failed
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AI-3 Document Analyzer", version="0.4")


# === Async Job Management ===

class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisJob(BaseModel):
    job_id: str
    status: str
    filename: Optional[str] = None
    created_at: str
    updated_at: str
    progress_pct: int = 0
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# In-memory job store (voor productie: Redis)
_jobs: Dict[str, AnalysisJob] = {}
_job_lock = threading.Lock()


def create_job(filename: Optional[str] = None) -> AnalysisJob:
    """Maak een nieuwe analyse job."""
    job_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    
    job = AnalysisJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        filename=filename,
        created_at=now,
        updated_at=now,
    )
    
    with _job_lock:
        _jobs[job_id] = job
    
    return job


def update_job(
    job_id: str,
    status: Optional[str] = None,
    progress_pct: Optional[int] = None,
    message: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
):
    """Update een bestaande job."""
    with _job_lock:
        if job_id not in _jobs:
            return
        
        job = _jobs[job_id]
        if status:
            job.status = status
        if progress_pct is not None:
            job.progress_pct = progress_pct
        if message:
            job.message = message
        if result is not None:
            job.result = result
        if error:
            job.error = error
        
        job.updated_at = datetime.utcnow().isoformat()


def get_job(job_id: str) -> Optional[AnalysisJob]:
    """Haal job status op."""
    with _job_lock:
        return _jobs.get(job_id)


def cleanup_old_jobs(max_age_minutes: int = 60):
    """Verwijder oude jobs."""
    cutoff = datetime.utcnow()
    with _job_lock:
        to_delete = []
        for job_id, job in _jobs.items():
            created = datetime.fromisoformat(job.created_at)
            age_minutes = (cutoff - created).total_seconds() / 60
            if age_minutes > max_age_minutes and job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                to_delete.append(job_id)
        
        for job_id in to_delete:
            del _jobs[job_id]


def run_analysis_job(
    job_id: str,
    document: str,
    filename: Optional[str],
    mime_type: Optional[str],
    force_parallel: bool = False,
):
    """
    Voer analyse uit in background thread.
    Stuurt webhooks naar AI-4 voor progress updates.
    
    Na analyse: cleanup GPU's zodat volgende taak (ingest/embed) schone GPU's heeft.
    """
    try:
        # Update status
        update_job(job_id, status=JobStatus.PROCESSING, progress_pct=5, message="Starting analysis")
        report_analyzing(job_id, model="llama3.1:70b")
        
        # Bepaal analyse type
        use_parallel = force_parallel or should_use_parallel_analysis(document, filename)
        
        if use_parallel:
            update_job(job_id, progress_pct=10, message="Using parallel analysis (large document)")
            logger.info(f"[Job {job_id}] PARALLEL analysis for {filename}")
            analysis = parallel_analyze_document(
                text=document,
                filename=filename,
                mime_type=mime_type,
            )
        else:
            update_job(job_id, progress_pct=10, message="Using single analysis")
            logger.info(f"[Job {job_id}] SINGLE analysis for {filename}")
            analysis = analyze_document(
                text=document,
                filename=filename,
                mime_type=mime_type,
            )
        
        # === GPU CLEANUP: Maak GPU's schoon na 70B analyse ===
        # Dit zorgt dat de volgende taak (ingest/embedding) schone GPU's heeft
        logger.info(f"[Job {job_id}] Cleaning GPU's after 70B analysis...")
        gpu_manager.unload_ollama_models()
        gpu_manager.cleanup_pytorch()
        
        # Success
        result = analysis.model_dump() if hasattr(analysis, 'model_dump') else analysis.__dict__
        update_job(job_id, status=JobStatus.COMPLETED, progress_pct=100, 
                   message="Analysis completed", result=result)
        report_completed(job_id, chunks_stored=0)
        
        logger.info(f"[Job {job_id}] Completed successfully (GPU's cleaned)")
        
    except Exception as e:
        error_msg = str(e)
        update_job(job_id, status=JobStatus.FAILED, error=error_msg, message=f"Failed: {error_msg[:100]}")
        report_failed(job_id, error=error_msg, stage="analysis")
        logger.exception(f"[Job {job_id}] Failed: {e}")
        
        # Ook bij fouten: cleanup GPU's
        try:
            gpu_manager.unload_ollama_models()
            gpu_manager.cleanup_pytorch()
        except Exception as cleanup_err:
            logger.warning(f"[Job {job_id}] GPU cleanup after error failed: {cleanup_err}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai3-doc-analyzer"}


@app.get("/gpu/status")
async def gpu_status():
    """GPU status voor monitoring."""
    status = gpu_manager.get_status()
    temps = gpu_manager.get_gpu_temperatures()
    
    # Voeg temperaturen toe aan GPU info
    for gpu in status.get("gpus", []):
        gpu["temperature_c"] = temps.get(gpu["index"], 0)
    
    return status


@app.get("/gpu/temperatures")
async def gpu_temperatures():
    """Haal alleen GPU temperaturen op."""
    temps = gpu_manager.get_gpu_temperatures()
    free_gpus = gpu_manager.get_free_gpus(min_free_mb=6000, max_temp=75)
    
    return {
        "temperatures": temps,
        "free_gpus": free_gpus,
        "gpu_count": gpu_manager._gpu_count,
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    Analyseer document - kiest automatisch parallel of single-GPU analyse.
    
    Parallel analyse wordt gebruikt wanneer:
    - Document groter dan 3MB
    - Document meer dan 50 pagina's
    
    Dit verdeelt werk over meerdere GPU's om thermal throttling te voorkomen.
    """
    try:
        # Check of we parallel moeten analyseren
        if should_use_parallel_analysis(req.document, req.filename):
            logger.info(f"[Analyzer] Using PARALLEL analysis for {req.filename}")
            analysis = parallel_analyze_document(
                text=req.document,
                filename=req.filename,
                mime_type=req.mime_type,
            )
        else:
            logger.info(f"[Analyzer] Using SINGLE analysis for {req.filename}")
            analysis = analyze_document(
                text=req.document,
                filename=req.filename,
                mime_type=req.mime_type,
            )
        
        return AnalyzeResponse(analysis=analysis)
        
    except Exception as e:
        logger.exception(f"[Analyzer] Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"analysis_failed: {e}")


@app.post("/analyze/parallel", response_model=AnalyzeResponse)
async def analyze_parallel(req: AnalyzeRequest):
    """
    Forceer parallel analyse - altijd over meerdere GPU's.
    Nuttig voor testing of wanneer je expliciet parallel wilt.
    """
    try:
        logger.info(f"[Analyzer] FORCED PARALLEL analysis for {req.filename}")
        analysis = parallel_analyze_document(
            text=req.document,
            filename=req.filename,
            mime_type=req.mime_type,
        )
        return AnalyzeResponse(analysis=analysis)
    except Exception as e:
        logger.exception(f"[Analyzer] Parallel analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"parallel_analysis_failed: {e}")


# === ASYNC JOB ENDPOINTS ===
# Voor lange analyses: AI-4 krijgt direct een job_id terug en pollt status

class AsyncAnalyzeResponse(BaseModel):
    job_id: str
    status: str
    message: str


@app.post("/analyze/async", response_model=AsyncAnalyzeResponse)
async def analyze_async(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Start async analyse - retourneert direct met job_id.
    
    AI-4 kan dan:
    1. Pollen via GET /analyze/status/{job_id}
    2. Wachten op webhook (als geconfigureerd)
    
    Dit voorkomt HTTP timeouts bij grote documenten.
    
    Response:
        {"job_id": "abc123", "status": "pending", "message": "Job created"}
    """
    # Maak job aan
    job = create_job(filename=req.filename)
    report_received(job.job_id, filename=req.filename)
    
    # Start analyse in background
    background_tasks.add_task(
        run_analysis_job,
        job.job_id,
        req.document,
        req.filename,
        req.mime_type,
        False,  # force_parallel
    )
    
    logger.info(f"[Analyzer] Async job {job.job_id} created for {req.filename}")
    
    return AsyncAnalyzeResponse(
        job_id=job.job_id,
        status=JobStatus.PENDING,
        message=f"Analysis job created. Poll /analyze/status/{job.job_id} for progress."
    )


@app.post("/analyze/async/parallel", response_model=AsyncAnalyzeResponse)
async def analyze_async_parallel(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Start async PARALLEL analyse - altijd over meerdere GPU's.
    """
    job = create_job(filename=req.filename)
    report_received(job.job_id, filename=req.filename)
    
    background_tasks.add_task(
        run_analysis_job,
        job.job_id,
        req.document,
        req.filename,
        req.mime_type,
        True,  # force_parallel
    )
    
    logger.info(f"[Analyzer] Async PARALLEL job {job.job_id} created for {req.filename}")
    
    return AsyncAnalyzeResponse(
        job_id=job.job_id,
        status=JobStatus.PENDING,
        message=f"Parallel analysis job created. Poll /analyze/status/{job.job_id} for progress."
    )


@app.get("/analyze/status/{job_id}")
async def get_analysis_status(job_id: str):
    """
    Haal status op van een async analyse job.
    
    Returns:
        - status: pending | processing | completed | failed
        - progress_pct: 0-100
        - message: Human readable status
        - result: DocumentAnalysis als completed
        - error: Error message als failed
    
    AI-4 poll strategie:
        - Poll elke 2 seconden
        - Stop als status == "completed" of "failed"
        - Timeout na 10 minuten
    """
    job = get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "message": job.message,
        "filename": job.filename,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "result": job.result,
        "error": job.error,
    }


@app.get("/analyze/jobs")
async def list_analysis_jobs():
    """
    Lijst alle actieve jobs.
    Nuttig voor debugging en monitoring.
    """
    # Cleanup oude jobs eerst
    cleanup_old_jobs(max_age_minutes=60)
    
    with _job_lock:
        jobs = [
            {
                "job_id": j.job_id,
                "status": j.status,
                "progress_pct": j.progress_pct,
                "filename": j.filename,
                "created_at": j.created_at,
            }
            for j in _jobs.values()
        ]
    
    return {
        "total_jobs": len(jobs),
        "jobs": jobs,
    }


@app.delete("/analyze/jobs/{job_id}")
async def cancel_job(job_id: str):
    """
    Annuleer/verwijder een job.
    Let op: kan een running job niet stoppen, alleen verwijderen uit lijst.
    """
    with _job_lock:
        if job_id in _jobs:
            del _jobs[job_id]
            return {"status": "deleted", "job_id": job_id}
    
    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
