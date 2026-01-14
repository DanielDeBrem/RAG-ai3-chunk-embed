"""
Free Text Chunking Strategy

Geoptimaliseerd voor vrije, ongestructureerde narratieve tekst.
Denk aan: artikelen, verhalen, rapporten, essays, blogs.

Focus op:
- Behoud van semantische samenhang
- Respect voor zinsgrenzen
- Paragraaf integriteit
- Natuurlijke leesflow
"""
import re
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class FreeTextStrategy(ChunkStrategy):
    """
    Chunking strategie voor vrije narratieve tekst.
    
    Kenmerken:
    - Split bij voorkeur op paragrafen
    - Respecteer altijd zinsgrenzen (nooit mid-sentence)
    - Gebruik overlap voor context continuïteit
    - Detecteert lopende tekst vs. gestructureerde content
    """
    
    name = "free_text"
    description = "Optimized for narrative, unstructured text (articles, stories, reports)"
    default_config = {
        "max_chars": 1000,
        "overlap": 150,
        "min_chunk_chars": 200,
        "preserve_sentences": True
    }
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer of dit vrije narratieve tekst is.
        
        Indicatoren:
        - Hoge ratio complete zinnen
        - Lange paragrafen
        - Weinig structuur markers (headers, lists, tables)
        - Normale zinslengte (niet te kort, niet te lang)
        """
        sample = text[:2000]
        metadata = metadata or {}
        
        score = 0.5  # Base score
        
        # Check: zijn er veel complete zinnen?
        sentences = re.split(r'[.!?]+\s+', sample)
        complete_sentences = [s for s in sentences if len(s) > 20 and len(s) < 200]
        if len(complete_sentences) >= 5:
            score += 0.2
        
        # Check: lange paragrafen (teken van narratieve tekst)
        paragraphs = [p.strip() for p in sample.split('\n\n') if p.strip()]
        if paragraphs:
            avg_para_length = sum(len(p) for p in paragraphs) / len(paragraphs)
            if avg_para_length > 200:
                score += 0.15
        
        # Penaliseer structuur markers
        structure_markers = [
            r'^\s*#{1,3}\s+',  # Markdown headers
            r'^\s*[\*\-\+]\s+',  # Lists
            r'^\s*\d+[\.\)]\s+',  # Numbered lists
            r'\[PAGE\s+\d+\]',  # Page markers
            r'^[\|\+\-].*[\|\+\-]$',  # Tables
        ]
        
        for pattern in structure_markers:
            matches = len(re.findall(pattern, sample, re.MULTILINE))
            if matches > 3:
                score -= 0.1
        
        # Bonus voor typische narrative woorden
        narrative_indicators = [
            'vertelde', 'zei', 'dacht', 'vroeg', 'antwoordde',
            'echter', 'daarom', 'bovendien', 'namelijk',
            'vervolgens', 'daarna', 'toen', 'plotseling'
        ]
        narrative_count = sum(sample.lower().count(word) for word in narrative_indicators)
        if narrative_count > 2:
            score += 0.1
        
        # Check filename hints
        fn = metadata.get("filename", "").lower()
        text_hints = ["artikel", "verhaal", "essay", "blog", "rapport", "notitie"]
        if any(hint in fn for hint in text_hints):
            score += 0.1
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk vrije tekst met respect voor semantische eenheden.
        
        Algoritme:
        1. Split op paragrafen
        2. Per paragraaf: split op zinnen indien nodig
        3. Bouw chunks op tot max_chars
        4. Zorg voor overlap voor context
        5. Vermijd te kleine chunks (merge indien mogelijk)
        """
        min_chunk = config.extra_params.get("min_chunk_chars", 200)
        preserve_sentences = config.extra_params.get("preserve_sentences", True)
        
        # Split op paragrafen
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        if not paragraphs:
            return [text.strip()] if text.strip() else []
        
        chunks: List[str] = []
        current_chunk = ""
        
        for para in paragraphs:
            # Check of paragraaf in huidige chunk past
            potential_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            
            if len(potential_chunk) <= config.max_chars:
                # Past nog, voeg toe
                current_chunk = potential_chunk
            else:
                # Past niet meer
                if current_chunk:
                    # Sla huidige chunk op
                    chunks.append(current_chunk)
                    
                    # Bereid overlap voor
                    overlap_text = self._get_overlap_text(
                        current_chunk, 
                        config.overlap, 
                        preserve_sentences
                    )
                    current_chunk = f"{overlap_text}\n\n{para}" if overlap_text else para
                else:
                    # Eerste paragraaf was al te groot
                    # Split paragraaf op zinnen indien preserve_sentences
                    if preserve_sentences and len(para) > config.max_chars:
                        sub_chunks = self._split_by_sentences(para, config)
                        chunks.extend(sub_chunks[:-1])
                        current_chunk = sub_chunks[-1] if sub_chunks else para
                    else:
                        current_chunk = para
        
        # Laatste chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        # Post-processing: merge te kleine chunks
        chunks = self._merge_small_chunks(chunks, min_chunk)
        
        return chunks if chunks else [text.strip()]
    
    def _get_overlap_text(self, text: str, overlap_size: int, preserve_sentences: bool) -> str:
        """
        Haal overlap tekst op van het einde van de text.
        Bij preserve_sentences: pak complete zinnen.
        """
        if overlap_size == 0:
            return ""
        
        if not preserve_sentences:
            return text[-overlap_size:] if len(text) > overlap_size else text
        
        # Pak complete zinnen vanaf het einde
        sentences = re.split(r'([.!?]+\s+)', text)
        overlap_parts = []
        char_count = 0
        
        # Ga van achter naar voren
        for i in range(len(sentences) - 1, -1, -1):
            part = sentences[i]
            if char_count + len(part) <= overlap_size:
                overlap_parts.insert(0, part)
                char_count += len(part)
            else:
                break
        
        return ''.join(overlap_parts).strip()
    
    def _split_by_sentences(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Split tekst op zinnen, respecteer max_chars.
        """
        # Split op zinseindes
        sentences = re.split(r'([.!?]+\s+)', text)
        
        chunks: List[str] = []
        current = ""
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            full_sentence = sentence + punctuation
            
            if len(current) + len(full_sentence) <= config.max_chars:
                current += full_sentence
            else:
                if current:
                    chunks.append(current.strip())
                current = full_sentence
        
        if current:
            chunks.append(current.strip())
        
        return chunks if chunks else [text]
    
    def _merge_small_chunks(self, chunks: List[str], min_size: int) -> List[str]:
        """
        Merge te kleine chunks met hun buren voor betere semantische eenheden.
        """
        if not chunks or min_size <= 0:
            return chunks
        
        merged: List[str] = []
        i = 0
        
        while i < len(chunks):
            current = chunks[i]
            
            # Als te klein en er is een volgende chunk, probeer te mergen
            if len(current) < min_size and i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                combined = f"{current}\n\n{next_chunk}"
                
                # Merge alleen als gecombineerde chunk niet te groot is
                if len(combined) <= min_size * 3:  # Max 3x min_size
                    merged.append(combined)
                    i += 2  # Skip beide chunks
                else:
                    merged.append(current)
                    i += 1
            else:
                merged.append(current)
                i += 1
        
        return merged
