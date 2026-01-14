#!/usr/bin/env python3
"""
OCR Service for AI-3 DataFactory
=================================

GPU-accelerated OCR service using EasyOCR for scanned document text extraction.
Runs on GPU 2 (CUDA_VISIBLE_DEVICES=2).

Features:
- Multi-language support (Dutch + English)
- PDF page-by-page processing
- Confidence scoring
- Layout preservation
- Fast GPU processing (~6x faster than Tesseract)

Port: 9300
GPU: 2
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import uvicorn

# OCR imports
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("WARNING: EasyOCR not installed. Install with: pip install easyocr")

# PDF/Image processing
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    print("WARNING: pdf2image not installed. Install with: pip install pdf2image")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI-3 OCR Service", version="1.0")

# Global OCR reader (loaded once at startup)
ocr_reader: Optional[easyocr.Reader] = None


class OCRRequest(BaseModel):
    """OCR extraction request."""
    languages: List[str] = ["nl", "en"]
    min_confidence: float = 0.3
    preserve_layout: bool = True


class OCRResult(BaseModel):
    """OCR extraction result."""
    text: str
    confidence: float
    page_count: int
    pages: List[Dict[str, Any]]
    language_detected: str


@app.on_event("startup")
async def startup_event():
    """Load OCR model on GPU at startup."""
    global ocr_reader
    
    if not EASYOCR_AVAILABLE:
        logger.error("EasyOCR not available! Service will not function.")
        return
    
    logger.info("[OCR] Loading EasyOCR model on GPU...")
    try:
        # EasyOCR will use GPU if CUDA is available
        # CUDA_VISIBLE_DEVICES should be set to 2 by startup script
        ocr_reader = easyocr.Reader(
            ['nl', 'en'],
            gpu=True,
            verbose=False
        )
        logger.info("[OCR] ✅ EasyOCR loaded successfully on GPU")
    except Exception as e:
        logger.error(f"[OCR] ❌ Failed to load EasyOCR: {e}")
        ocr_reader = None


@app.get("/health")
async def health():
    """Health check endpoint."""
    status = "ok" if ocr_reader is not None else "degraded"
    return {
        "status": status,
        "service": "ocr",
        "gpu": "2",
        "easyocr_ready": ocr_reader is not None,
        "pdf2image_available": PDF2IMAGE_AVAILABLE
    }


@app.post("/ocr/extract", response_model=OCRResult)
async def extract_text(
    file: UploadFile = File(...),
    min_confidence: float = 0.3,
    preserve_layout: bool = True
):
    """
    Extract text from scanned PDF or image using OCR.
    
    Supports:
    - PDF files (processed page-by-page)
    - Image files (PNG, JPG, TIFF)
    
    Returns:
    - Full text from all pages
    - Per-page results with confidence scores
    - Layout preservation (optional)
    """
    if ocr_reader is None:
        raise HTTPException(status_code=503, detail="OCR service not ready")
    
    # Read uploaded file
    content = await file.read()
    
    # Determine file type
    file_ext = Path(file.filename).suffix.lower()
    
    try:
        if file_ext == '.pdf':
            # Process PDF
            result = await process_pdf(content, min_confidence, preserve_layout)
        elif file_ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            # Process single image
            result = await process_image(content, min_confidence, preserve_layout)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_ext}"
            )
        
        return result
        
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_pdf(
    pdf_bytes: bytes,
    min_confidence: float,
    preserve_layout: bool
) -> OCRResult:
    """Process PDF file page by page."""
    if not PDF2IMAGE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="pdf2image not available. Cannot process PDFs."
        )
    
    # Save PDF to temp file (pdf2image needs file path)
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    
    try:
        # Convert PDF pages to images
        images = convert_from_path(tmp_path, dpi=300)
        logger.info(f"[OCR] Processing PDF with {len(images)} pages")
        
        pages_results = []
        all_text = []
        total_confidence = 0.0
        
        for page_num, image in enumerate(images, 1):
            # Run OCR on page
            results = ocr_reader.readtext(image)
            
            # Filter by confidence
            filtered_results = [
                r for r in results 
                if r[2] >= min_confidence
            ]
            
            # Extract text
            if preserve_layout:
                # Sort by Y coordinate (top to bottom)
                sorted_results = sorted(filtered_results, key=lambda x: x[0][0][1])
                page_text = "\n".join([r[1] for r in sorted_results])
            else:
                page_text = " ".join([r[1] for r in filtered_results])
            
            # Calculate average confidence for page
            if filtered_results:
                page_confidence = sum(r[2] for r in filtered_results) / len(filtered_results)
            else:
                page_confidence = 0.0
            
            pages_results.append({
                "page_number": page_num,
                "text": page_text,
                "confidence": page_confidence,
                "detections": len(filtered_results)
            })
            
            all_text.append(page_text)
            total_confidence += page_confidence
        
        # Combine all pages
        full_text = "\n\n".join(all_text)
        avg_confidence = total_confidence / len(pages_results) if pages_results else 0.0
        
        return OCRResult(
            text=full_text,
            confidence=avg_confidence,
            page_count=len(pages_results),
            pages=pages_results,
            language_detected="nl/en"
        )
        
    finally:
        # Cleanup temp file
        os.unlink(tmp_path)


async def process_image(
    image_bytes: bytes,
    min_confidence: float,
    preserve_layout: bool
) -> OCRResult:
    """Process single image file."""
    if not PIL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="PIL not available. Cannot process images."
        )
    
    # Load image
    image = Image.open(io.BytesIO(image_bytes))
    
    # Run OCR
    results = ocr_reader.readtext(image)
    
    # Filter by confidence
    filtered_results = [
        r for r in results 
        if r[2] >= min_confidence
    ]
    
    # Extract text
    if preserve_layout:
        sorted_results = sorted(filtered_results, key=lambda x: x[0][0][1])
        text = "\n".join([r[1] for r in sorted_results])
    else:
        text = " ".join([r[1] for r in filtered_results])
    
    # Calculate confidence
    if filtered_results:
        confidence = sum(r[2] for r in filtered_results) / len(filtered_results)
    else:
        confidence = 0.0
    
    return OCRResult(
        text=text,
        confidence=confidence,
        page_count=1,
        pages=[{
            "page_number": 1,
            "text": text,
            "confidence": confidence,
            "detections": len(filtered_results)
        }],
        language_detected="nl/en"
    )


@app.post("/ocr/test")
async def test_ocr():
    """Simple OCR test endpoint."""
    if ocr_reader is None:
        return {"status": "error", "message": "OCR not ready"}
    
    return {
        "status": "ok",
        "message": "OCR service is ready",
        "languages": ["nl", "en"],
        "gpu_enabled": True
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9300)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )
