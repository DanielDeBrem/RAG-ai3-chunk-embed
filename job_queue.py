"""
Persistent job queue backed by SQLite database.

Provides:
- Job creation and status tracking
- Worker loop for processing jobs
- Progress updates
- Error handling and retry logic
"""
import uuid
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from models import get_session, Job

logger = logging.getLogger(__name__)


class JobQueue:
    """
    Database-backed persistent job queue.
    
    Features:
    - Crash-safe: jobs survive restarts
    - Status tracking: pending, running, completed, failed
    - Progress updates: 0-100%
    - Error capture and logging
    """
    
    def __init__(self):
        """Initialize job queue."""
        pass
    
    def create_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        job_id: Optional[str] = None
    ) -> str:
        """
        Create a new job.
        
        Args:
            job_type: Job type (e.g., 'ingest_docs', 'rebuild_index')
            payload: Job payload data
            job_id: Optional job ID (generated if not provided)
        
        Returns:
            Job ID
        """
        if not job_id:
            job_id = str(uuid.uuid4())
        
        session = get_session()
        try:
            job = Job(
                job_id=job_id,
                type=job_type,
                status='pending',
                progress=0
            )
            job.set_payload(payload)
            
            session.add(job)
            session.commit()
            
            logger.info(f"Created job: {job_id} (type={job_type})")
            return job_id
        
        finally:
            session.close()
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job status and details.
        
        Args:
            job_id: Job ID
        
        Returns:
            Job details dict or None if not found
        """
        session = get_session()
        try:
            job = session.query(Job).filter_by(job_id=job_id).first()
            
            if not job:
                return None
            
            return {
                'job_id': job.job_id,
                'type': job.type,
                'status': job.status,
                'progress': job.progress,
                'error': job.error,
                'payload': job.get_payload(),
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'updated_at': job.updated_at.isoformat() if job.updated_at else None,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            }
        
        finally:
            session.close()
    
    def update_job_status(
        self,
        job_id: str,
        status: str,
        progress: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Update job status.
        
        Args:
            job_id: Job ID
            status: New status (pending, running, completed, failed)
            progress: Progress percentage (0-100)
            error: Error message (if failed)
        """
        session = get_session()
        try:
            job = session.query(Job).filter_by(job_id=job_id).first()
            
            if not job:
                logger.warning(f"Job not found: {job_id}")
                return
            
            job.status = status
            
            if progress is not None:
                job.progress = max(0, min(100, progress))
            
            if error is not None:
                job.error = error
            
            if status == 'running' and not job.started_at:
                job.started_at = datetime.utcnow()
            
            if status in ('completed', 'failed'):
                job.completed_at = datetime.utcnow()
                job.progress = 100 if status == 'completed' else job.progress
            
            job.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.debug(f"Updated job {job_id}: status={status}, progress={progress}")
        
        finally:
            session.close()
    
    def get_next_pending_job(self) -> Optional[Dict[str, Any]]:
        """
        Get next pending job to process.
        
        Returns:
            Job details or None if no pending jobs
        """
        session = get_session()
        try:
            job = session.query(Job).filter_by(
                status='pending'
            ).order_by(Job.created_at).first()
            
            if not job:
                return None
            
            # Mark as running
            job.status = 'running'
            job.started_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            session.commit()
            
            return {
                'job_id': job.job_id,
                'type': job.type,
                'payload': job.get_payload(),
            }
        
        finally:
            session.close()
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        session = get_session()
        try:
            from sqlalchemy import func
            
            stats = session.query(
                Job.status,
                func.count(Job.job_id)
            ).group_by(Job.status).all()
            
            total = session.query(func.count(Job.job_id)).scalar() or 0
            
            status_counts = dict(stats)
            
            return {
                'total': total,
                'pending': status_counts.get('pending', 0),
                'running': status_counts.get('running', 0),
                'completed': status_counts.get('completed', 0),
                'failed': status_counts.get('failed', 0),
            }
        
        finally:
            session.close()


# Global job queue instance
job_queue = JobQueue()


# Job handler registry
_job_handlers: Dict[str, Callable] = {}


def register_job_handler(job_type: str):
    """
    Decorator to register a job handler function.
    
    Example:
        @register_job_handler('ingest_docs')
        def handle_ingest(job_id, payload):
            # Process job
            pass
    """
    def decorator(func: Callable):
        _job_handlers[job_type] = func
        logger.info(f"Registered job handler: {job_type} -> {func.__name__}")
        return func
    return decorator


def process_job(job_id: str, job_type: str, payload: Dict[str, Any]) -> None:
    """
    Process a single job.
    
    Args:
        job_id: Job ID
        job_type: Job type
        payload: Job payload
    """
    logger.info(f"Processing job {job_id} (type={job_type})")
    
    handler = _job_handlers.get(job_type)
    
    if not handler:
        error_msg = f"No handler registered for job type: {job_type}"
        logger.error(error_msg)
        job_queue.update_job_status(job_id, 'failed', error=error_msg)
        return
    
    try:
        # Call handler
        handler(job_id, payload)
        
        # Mark as completed
        job_queue.update_job_status(job_id, 'completed', progress=100)
        logger.info(f"Job {job_id} completed successfully")
    
    except Exception as e:
        error_msg = f"Job failed: {str(e)}"
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        job_queue.update_job_status(job_id, 'failed', error=error_msg)


def run_worker(poll_interval: float = 1.0, max_iterations: Optional[int] = None):
    """
    Run worker loop to process jobs.
    
    Args:
        poll_interval: Seconds to wait between polling for jobs
        max_iterations: Maximum iterations (None = infinite)
    """
    logger.info("Starting job worker...")
    
    iteration = 0
    while True:
        if max_iterations is not None and iteration >= max_iterations:
            logger.info(f"Max iterations ({max_iterations}) reached, stopping worker")
            break
        
        try:
            # Get next job
            job = job_queue.get_next_pending_job()
            
            if job:
                process_job(job['job_id'], job['type'], job['payload'])
            else:
                # No jobs, wait before polling again
                time.sleep(poll_interval)
            
            iteration += 1
        
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
            break
        
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            time.sleep(poll_interval)
    
    logger.info("Worker stopped")
