#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$ROOT"

BACKUP_DIR="$ROOT/backup_doc_type_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f doc_type_classifier.py ]; then
  cp doc_type_classifier.py "$BACKUP_DIR/doc_type_classifier.py"
fi

echo "Backup van doc_type_classifier.py in $BACKUP_DIR"

cat > doc_type_classifier.py << 'PY'
from __future__ import annotations

from typing import Optional


def _basic_classify(text: str,
                    filename: Optional[str] = None,
                    mime_type: Optional[str] = None) -> str:
    """
    Simpele heuristische documenttype-classifier.
    """
    lower = text.lower()

    # Jaarrekeningen / jaarverslagen
    if "jaarrekening" in lower or "balans" in lower or "winst- en verliesrekening" in lower:
        if (mime_type == "application/pdf") or (filename and filename.lower().endswith(".pdf")):
            return "annual_report_pdf"
        return "annual_report"

    # Offertes / sales documenten
    if any(w in lower for w in ["offerte", "aanbieding", "prijs", "tarief"]):
        return "offer_doc"

    # Coaching / hulpverlening
    if any(w in lower for w in ["coaching", "coachingsgesprek", "sessie", "client", "cliënt"]):
        return "coaching_doc"

    # Reviews
    if any(w in lower for w in ["review", "beoordeling", "ster", "ervaring", "recensie"]):
        return "review_doc"

    # Chatlogs
    if any(w in lower for w in ["user:", "assistant:", "client:", "therapist:"]):
        return "chatlog"

    # Fallback
    return "generic_doc"


def classify_document(*args, **kwargs) -> str:
    """
    Compat-laag:
    - ondersteunt:
        classify_document(text=..., filename=..., mime_type=...)
        classify_document(document=..., filename=..., mime_type=...)
    - en positional eerste argument als tekst.
    """
    text: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None

    # Positional args
    if args:
        text = args[0]
        if len(args) > 1:
            filename = args[1]
        if len(args) > 2:
            mime_type = args[2]

    # Keyword args (oude en nieuwe namen)
    if "document" in kwargs and text is None:
        text = kwargs.pop("document")
    if "text" in kwargs and text is None:
        text = kwargs.pop("text")

    if "filename" in kwargs and filename is None:
        filename = kwargs.pop("filename")
    if "mime_type" in kwargs and mime_type is None:
        mime_type = kwargs.pop("mime_type")

    if text is None:
        raise ValueError("classify_document requires 'text' or 'document'")

    return _basic_classify(text, filename=filename, mime_type=mime_type)
PY

echo "doc_type_classifier.py opnieuw geschreven (compatibel met 'text=' én 'document=')."
