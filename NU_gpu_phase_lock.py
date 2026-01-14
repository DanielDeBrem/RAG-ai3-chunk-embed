"""gpu_phase_lock.py

Inter-process GPU exclusive lock.

Waarom:
- We hebben meerdere services (uvicorn processen) die GPU gebruiken.
- Een in-proces GPUManager kan geen sequentie afdwingen tussen processen.

Deze lock zorgt ervoor dat er maximaal 1 "GPU job" tegelijk draait.

Gebruik:
    from gpu_phase_lock import gpu_exclusive_lock

    with gpu_exclusive_lock("embedding", doc_id="doc123", timeout_sec=600):
        ...

Lock file default:
    /tmp/ai3_gpu_exclusive.lock
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

try:
    import fcntl  # Linux-only (OK for this host)
    FCNTL_AVAILABLE = True
except Exception:
    FCNTL_AVAILABLE = False


logger = logging.getLogger(__name__)


@dataclass
class LockInfo:
    phase: str
    doc_id: Optional[str]
    pid: int
    acquired_at: float


class GPUExclusiveLock:
    def __init__(
        self,
        phase: str,
        doc_id: Optional[str] = None,
        lock_path: Optional[str] = None,
        timeout_sec: int = 900,
        poll_interval_sec: float = 0.25,
    ):
        self.phase = phase
        self.doc_id = doc_id
        self.lock_path = lock_path or os.getenv("AI3_GPU_LOCK_PATH", "/tmp/ai3_gpu_exclusive.lock")
        self.timeout_sec = int(os.getenv("AI3_GPU_LOCK_TIMEOUT_SEC", str(timeout_sec)))
        self.poll_interval_sec = poll_interval_sec
        self._fh = None
        self.info: Optional[LockInfo] = None

    def acquire(self) -> bool:
        if not FCNTL_AVAILABLE:
            logger.warning("fcntl not available; GPUExclusiveLock is disabled")
            return True

        os.makedirs(os.path.dirname(self.lock_path) or "/tmp", exist_ok=True)
        start = time.time()

        # open file once; keep handle
        self._fh = open(self.lock_path, "a+", encoding="utf-8")

        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.info = LockInfo(
                    phase=self.phase,
                    doc_id=self.doc_id,
                    pid=os.getpid(),
                    acquired_at=time.time(),
                )
                # write marker (best-effort)
                try:
                    self._fh.seek(0)
                    self._fh.truncate(0)
                    self._fh.write(
                        f"pid={self.info.pid} phase={self.phase} doc_id={self.doc_id or ''} acquired_at={int(self.info.acquired_at)}\n"
                    )
                    self._fh.flush()
                except Exception:
                    pass

                logger.info(
                    "[GPU LOCK] acquired phase=%s doc_id=%s pid=%s",
                    self.phase,
                    self.doc_id,
                    self.info.pid,
                )
                return True
            except BlockingIOError:
                if time.time() - start > self.timeout_sec:
                    raise TimeoutError(
                        f"GPU lock timeout after {self.timeout_sec}s (phase={self.phase}, doc_id={self.doc_id})"
                    )
                time.sleep(self.poll_interval_sec)

    def release(self):
        if not FCNTL_AVAILABLE:
            return
        if not self._fh:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            if self.info:
                duration = time.time() - self.info.acquired_at
                logger.info(
                    "[GPU LOCK] released phase=%s doc_id=%s duration=%.1fs",
                    self.info.phase,
                    self.info.doc_id,
                    duration,
                )
            self.info = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def gpu_exclusive_lock(
    phase: str,
    doc_id: Optional[str] = None,
    timeout_sec: int = 900,
    lock_path: Optional[str] = None,
) -> GPUExclusiveLock:
    return GPUExclusiveLock(
        phase=phase,
        doc_id=doc_id,
        timeout_sec=timeout_sec,
        lock_path=lock_path,
    )
