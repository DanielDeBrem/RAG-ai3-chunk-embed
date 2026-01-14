"""
Default Chunking Strategy

Basis paragraph-based chunking met optionele overlap.
Deze strategie werkt als fallback voor alle documenttypen.
"""
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class DefaultStrategy(ChunkStrategy):
    """
    Standaard paragraph-based chunking.
    
    Split op dubbele newlines (paragrafen) en bouw chunks op tot max_chars.
    Optioneel overlap tussen chunks voor context continuïteit.
    """
    
    name = "default"
    description = "Standard paragraph-based chunking with optional overlap"
    default_config = {"max_chars": 800, "overlap": 0}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Default strategie: altijd bruikbaar maar lage prioriteit.
        Wordt gebruikt als fallback wanneer geen specifieke strategie past.
        """
        return 0.3
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk op paragrafen met optionele overlap.
        
        Process:
        1. Split tekst op dubbele newlines (paragrafen)
        2. Bouw chunks op tot max_chars wordt bereikt
        3. Bij overflow: sla huidige chunk op en start nieuwe
        4. Optioneel: neem laatste N chars mee naar volgende chunk (overlap)
        """
        # Split op paragrafen
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        if not paras:
            return [text.strip()] if text.strip() else []
        
        chunks: List[str] = []
        buf = ""
        
        for p in paras:
            # Check of deze paragraaf past in huidige chunk
            if len(buf) + len(p) + 2 <= config.max_chars:
                buf = f"{buf}\n\n{p}" if buf else p
            else:
                # Chunk is vol, sla op
                if buf:
                    chunks.append(buf)
                    
                    # Overlap: neem laatste deel mee naar volgende chunk
                    if config.overlap > 0 and len(buf) > config.overlap:
                        buf = buf[-config.overlap:] + "\n\n" + p
                    else:
                        buf = p
                else:
                    # Eerste paragraaf was al te groot
                    buf = p
        
        # Laatste chunk toevoegen
        if buf:
            chunks.append(buf)
        
        # Safety: als geen chunks maar wel tekst, return tekst als is
        if not chunks and text.strip():
            chunks = [text.strip()]
        
        return chunks
