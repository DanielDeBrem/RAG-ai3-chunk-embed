"""
PDF OCR Extractor - Robuuste text extractie met automatische OCR fallback
"""
import os
import io
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PDFExtractionResult:
    """Result van PDF text extractie."""
    text: str
    pages: List[str]
    method: str  # "native", "ocr", "hybrid"
    page_count: int
    total_chars: int
    ocr_used: bool
    low_text_pages: List[int]  # Pagina's waar OCR gebruikt is


class PDFOCRExtractor:
    """
    Intelligente PDF text extractor met automatische OCR fallback.
    
    Strategie:
    1. Probeer native text extraction (pypdf)
    2. Detecteer pages met weinig/geen tekst (< MIN_CHARS_PER_PAGE)
    3. Gebruik OCR voor die pages
    4. Return hybride resultaat
    """
    
    # Threshold: als page minder dan dit heeft, gebruik OCR
    MIN_CHARS_PER_PAGE = 100
    
    # OCR configuratie
    OCR_LANGUAGES = "nld+eng"  # Nederlands + Engels
    OCR_DPI = 300  # Hogere DPI = betere kwaliteit, langzamer
    
    def __init__(self):
        self.pytesseract_available = self._check_pytesseract()
        self.pdf2image_available = self._check_pdf2image()
        
    def _check_pytesseract(self) -> bool:
        """Check of pytesseract beschikbaar is."""
        try:
            import pytesseract
            # Test of tesseract binary beschikbaar is
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract OCR found: version {version}")
            return True
        except Exception as e:
            logger.warning(f"Tesseract OCR not available: {e}")
            return False
    
    def _check_pdf2image(self) -> bool:
        """Check of pdf2image beschikbaar is."""
        try:
            import pdf2image
            return True
        except ImportError:
            logger.warning("pdf2image not available")
            return False
    
    def extract_text_native(self, pdf_data: bytes) -> Tuple[List[str], int]:
        """
        Extract tekst met pypdf (native).
        
        Returns:
            (pages, total_chars)
        """
        from pypdf import PdfReader
        
        reader = PdfReader(io.BytesIO(pdf_data))
        pages = []
        total_chars = 0
        
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append(text)
            total_chars += len(text.strip())
        
        logger.info(f"Native extraction: {len(pages)} pages, {total_chars} chars")
        return pages, total_chars
    
    def extract_page_with_ocr(self, pdf_data: bytes, page_num: int) -> str:
        """
        Extract single page met OCR.
        
        Args:
            pdf_data: PDF bytes
            page_num: Page number (0-indexed)
            
        Returns:
            Extracted text
        """
        if not self.pytesseract_available or not self.pdf2image_available:
            logger.warning(f"OCR not available for page {page_num}")
            return ""
        
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            
            # Convert specifieke page naar image
            images = convert_from_bytes(
                pdf_data,
                first_page=page_num + 1,
                last_page=page_num + 1,
                dpi=self.OCR_DPI,
            )
            
            if not images:
                logger.warning(f"No image generated for page {page_num}")
                return ""
            
            # OCR op image
            text = pytesseract.image_to_string(
                images[0],
                lang=self.OCR_LANGUAGES,
                config='--psm 1'  # Automatic page segmentation with OSD
            )
            
            logger.info(f"OCR page {page_num + 1}: {len(text)} chars extracted")
            return text
            
        except Exception as e:
            logger.error(f"OCR failed for page {page_num}: {e}")
            return ""
    
    def extract(self, pdf_data: bytes, force_ocr: bool = False) -> PDFExtractionResult:
        """
        Intelligente PDF text extractie met automatische OCR fallback.
        
        Args:
            pdf_data: PDF file als bytes
            force_ocr: Force OCR voor alle pages (override auto-detect)
            
        Returns:
            PDFExtractionResult met text, method info, etc.
        """
        # Stap 1: Native extraction
        logger.info("Starting PDF text extraction...")
        native_pages, total_native_chars = self.extract_text_native(pdf_data)
        page_count = len(native_pages)
        
        # Stap 2: Detecteer low-text pages
        low_text_pages = []
        avg_chars_per_page = total_native_chars / max(page_count, 1)
        
        if force_ocr:
            logger.info("Force OCR enabled - will OCR all pages")
            low_text_pages = list(range(page_count))
        else:
            for i, page_text in enumerate(native_pages):
                chars = len(page_text.strip())
                if chars < self.MIN_CHARS_PER_PAGE:
                    low_text_pages.append(i)
        
        logger.info(
            f"Detected {len(low_text_pages)}/{page_count} pages with low text "
            f"(avg: {avg_chars_per_page:.0f} chars/page)"
        )
        
        # Stap 3: OCR voor low-text pages (als beschikbaar)
        ocr_used = False
        final_pages = native_pages.copy()
        
        if low_text_pages and self.pytesseract_available and self.pdf2image_available:
            logger.info(f"Starting OCR for {len(low_text_pages)} pages...")
            ocr_used = True
            
            for idx, page_num in enumerate(low_text_pages):
                logger.info(f"OCR progress: {idx + 1}/{len(low_text_pages)} (page {page_num + 1})")
                ocr_text = self.extract_page_with_ocr(pdf_data, page_num)
                
                # Gebruik OCR tekst als het meer oplevert
                if len(ocr_text.strip()) > len(native_pages[page_num].strip()):
                    final_pages[page_num] = ocr_text
                    logger.info(f"  OCR improved page {page_num + 1}: {len(ocr_text)} chars")
        
        elif low_text_pages:
            logger.warning(
                f"{len(low_text_pages)} pages need OCR but OCR not available. "
                "Install: pip install pytesseract pdf2image && apt install tesseract-ocr tesseract-ocr-nld"
            )
        
        # Stap 4: Build final result
        full_text_parts = []
        for i, page_text in enumerate(final_pages):
            full_text_parts.append(f"[PAGE {i + 1}]\n{page_text}")
        
        full_text = "\n\n".join(full_text_parts)
        total_chars = sum(len(p.strip()) for p in final_pages)
        
        # Determine method
        if force_ocr or (low_text_pages and ocr_used):
            if len(low_text_pages) == page_count:
                method = "ocr"
            else:
                method = "hybrid"
        else:
            method = "native"
        
        result = PDFExtractionResult(
            text=full_text,
            pages=final_pages,
            method=method,
            page_count=page_count,
            total_chars=total_chars,
            ocr_used=ocr_used,
            low_text_pages=low_text_pages,
        )
        
        logger.info(
            f"PDF extraction completed: method={method}, pages={page_count}, "
            f"chars={total_chars}, ocr_pages={len(low_text_pages)}"
        )
        
        return result


# Global instance
_extractor = None


def get_pdf_ocr_extractor() -> PDFOCRExtractor:
    """Get global PDF OCR extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = PDFOCRExtractor()
    return _extractor


def extract_text_from_pdf_smart(pdf_data: bytes, force_ocr: bool = False) -> str:
    """
    Convenience function: extract text from PDF with smart OCR fallback.
    
    Args:
        pdf_data: PDF file bytes
        force_ocr: Force OCR mode
        
    Returns:
        Extracted text
    """
    extractor = get_pdf_ocr_extractor()
    result = extractor.extract(pdf_data, force_ocr=force_ocr)
    return result.text


def extract_text_from_pdf_with_info(pdf_data: bytes, force_ocr: bool = False) -> PDFExtractionResult:
    """
    Extract text from PDF with detailed extraction info.
    
    Args:
        pdf_data: PDF file bytes
        force_ocr: Force OCR mode
        
    Returns:
        PDFExtractionResult with full details
    """
    extractor = get_pdf_ocr_extractor()
    return extractor.extract(pdf_data, force_ocr=force_ocr)


# Installation check helper
def check_ocr_dependencies() -> dict:
    """
    Check OCR dependencies en return status.
    
    Returns:
        Dict met status info
    """
    status = {
        "pytesseract": False,
        "pdf2image": False,
        "tesseract_binary": False,
        "ready": False,
        "install_instructions": []
    }
    
    # Check pytesseract
    try:
        import pytesseract
        status["pytesseract"] = True
        
        # Check tesseract binary
        try:
            version = pytesseract.get_tesseract_version()
            status["tesseract_binary"] = True
            status["tesseract_version"] = str(version)
        except:
            status["install_instructions"].append(
                "Install Tesseract: sudo apt install tesseract-ocr tesseract-ocr-nld"
            )
    except ImportError:
        status["install_instructions"].append(
            "Install pytesseract: pip install pytesseract"
        )
    
    # Check pdf2image
    try:
        import pdf2image
        status["pdf2image"] = True
    except ImportError:
        status["install_instructions"].append(
            "Install pdf2image: pip install pdf2image"
        )
    
    status["ready"] = all([
        status["pytesseract"],
        status["pdf2image"],
        status["tesseract_binary"]
    ])
    
    return status


if __name__ == "__main__":
    # Test / diagnostic
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("PDF OCR Extractor - Dependency Check")
    print("=" * 60)
    
    status = check_ocr_dependencies()
    
    print(f"\nPython packages:")
    print(f"  pytesseract: {'✓' if status['pytesseract'] else '✗'}")
    print(f"  pdf2image:   {'✓' if status['pdf2image'] else '✗'}")
    
    print(f"\nSystem binaries:")
    print(f"  tesseract:   {'✓' if status['tesseract_binary'] else '✗'}")
    if status.get('tesseract_version'):
        print(f"    version: {status['tesseract_version']}")
    
    print(f"\nOCR Ready: {'✓ YES' if status['ready'] else '✗ NO'}")
    
    if status["install_instructions"]:
        print(f"\nInstallation needed:")
        for instr in status["install_instructions"]:
            print(f"  • {instr}")
    
    print("\n" + "=" * 60)
    
    # Test with sample PDF if provided
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"\nTesting with: {pdf_path}")
        
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
        
        result = extract_text_from_pdf_with_info(pdf_data)
        
        print(f"\nExtraction Result:")
        print(f"  Method: {result.method}")
        print(f"  Pages: {result.page_count}")
        print(f"  Total chars: {result.total_chars:,}")
        print(f"  OCR used: {result.ocr_used}")
        if result.low_text_pages:
            print(f"  OCR pages: {len(result.low_text_pages)} -> {result.low_text_pages[:10]}")
        
        print(f"\nFirst 500 chars:")
        print(result.text[:500])
