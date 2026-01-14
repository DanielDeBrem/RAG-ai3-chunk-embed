"""
Legal Documents Chunking Strategy

Geoptimaliseerd voor juridische en beleidsdocumenten.
Focus op contracten, algemene voorwaarden, wet- en regelgeving.

Kenmerken:
- Artikel-gebaseerde chunking (NIET semantisch)
- Hiërarchische structuur behouden (Art. 1.2.3)
- Subartikelen als aparte chunks
- GEEN overlap (juridische precisie)
- Volledige zinnen altijd bewaren
- Metadata extractie (artikelnummer, rechtsgebied, status)

Belangrijk: Juridische vragen zijn referentie-gedreven, niet verhalend.
"""
import re
from typing import List, Optional, Dict, Any, Tuple
from ..base import ChunkStrategy, ChunkingConfig


class LegalDocumentsStrategy(ChunkStrategy):
    """
    Chunking strategie voor juridische documenten.
    
    Ondersteunt:
    - Contracten
    - Algemene voorwaarden
    - Wet- en regelgeving
    - APV (Algemene Plaatselijke Verordening)
    - EU-richtlijnen
    - Subsidieregels
    - Beleidsregels
    """
    
    name = "legal"
    description = "Optimized for legal documents: contracts, terms, laws, regulations (article-based)"
    default_config = {
        "max_chars": 2000,  # Juridische artikelen kunnen lang zijn
        "overlap": 0,  # GEEN overlap voor juridische precisie
        "preserve_structure": True,
        "extract_metadata": True,
        "keep_full_sentences": True,
        "split_subarticles": True
    }
    
    # Artikel patterns (verschillende notaties)
    ARTICLE_PATTERNS = [
        r'(?:^|\n)\s*(Artikel|Art\.|Article|ARTIKEL)\s+(\d+[\.\d]*)',
        r'(?:^|\n)\s*§\s*(\d+[\.\d]*)',  # Paragraaf notatie
        r'(?:^|\n)\s*(\d+)\.\s+[A-Z]',  # Simpele nummering met hoofdletter start
    ]
    
    # Sub-artikel patterns (leden, sub-leden)
    SUBARTICLE_PATTERNS = [
        r'(?:^|\n)\s*(\d+)\.\s',  # 1. 2. 3.
        r'(?:^|\n)\s*([a-z])\)\s',  # a) b) c)
        r'(?:^|\n)\s*([a-z])\.\s',  # a. b. c.
        r'(?:^|\n)\s*\(([a-z0-9]+)\)\s',  # (1) (2) (a)
    ]
    
    # Legal terminologie
    LEGAL_TERMS = [
        r'(?i)\b(artikel|art\.|§|paragraaf|lid)\b',
        r'(?i)\b(bepaling|voorwaarde|verplichting)\b',
        r'(?i)\b(partij(?:en)?|contractant|schuldeiser)\b',
        r'(?i)\b(overeenkomst|contract|verbintenis)\b',
        r'(?i)\b(aansprakelijk(?:heid)?|schade|vordering)\b',
        r'(?i)\b(opzeggen|ontbinden|beëindigen)\b',
        r'(?i)\b(wet|wetgeving|regelgeving|richtlijn)\b',
        r'(?i)\b(rechtbank|rechter|arbitrage)\b',
        r'(?i)\b(dwingend|aanvullend|vernietigbaar)\b',
    ]
    
    # Rechtsgebied hints
    JURISDICTION_HINTS = [
        (r'(?i)(nederlands? recht|nederlandse? wet)', 'NL'),
        (r'(?i)(eu[- ]?richtlijn|europese? unie)', 'EU'),
        (r'(?i)(gemeente|gemeentelijk|APV)', 'Gemeente'),
        (r'(?i)(provinc(?:ie|iaal))', 'Provincie'),
        (r'(?i)(rijks|nationaal)', 'Nationaal'),
    ]
    
    # Status indicators
    STATUS_PATTERNS = [
        (r'(?i)(vervallen|ingetrokken|niet meer van kracht)', 'vervallen'),
        (r'(?i)(gewijzigd|aangepast)\s+(?:per|op)\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', 'gewijzigd'),
        (r'(?i)(geldig vanaf|in werking getreden)\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', 'actief'),
    ]
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer juridische documenten.
        
        Indicatoren:
        - Artikel nummering (Art. 1, § 2, etc.)
        - Juridische terminologie
        - Hiërarchische structuur
        - Formele taal
        - Rechtsgebied indicaties
        """
        sample = text[:3000]
        metadata = metadata or {}
        
        score = 0.3  # Base score
        
        # Check: artikel nummering
        article_count = 0
        for pattern in self.ARTICLE_PATTERNS:
            matches = re.findall(pattern, sample, re.MULTILINE | re.IGNORECASE)
            article_count += len(matches)
        
        if article_count >= 3:
            score += 0.35
        elif article_count >= 1:
            score += 0.2
        
        # Check: sub-artikel structuur
        subarticle_count = 0
        for pattern in self.SUBARTICLE_PATTERNS:
            matches = re.findall(pattern, sample, re.MULTILINE)
            subarticle_count += len(matches)
        
        if subarticle_count >= 5:
            score += 0.15
        
        # Check: juridische termen
        legal_term_count = sum(
            len(re.findall(pattern, sample))
            for pattern in self.LEGAL_TERMS
        )
        
        if legal_term_count >= 5:
            score += 0.2
        elif legal_term_count >= 3:
            score += 0.1
        
        # Check: rechtsgebied hints
        for pattern, _ in self.JURISDICTION_HINTS:
            if re.search(pattern, sample):
                score += 0.1
                break
        
        # Check: filename hints
        fn = metadata.get("filename", "").lower()
        legal_hints = [
            "contract", "overeenkomst", "voorwaarden", "algemene",
            "wet", "regeling", "apv", "verordening", "richtlijn",
            "subsidie", "beleid", "juridisch", "legal"
        ]
        if any(hint in fn for hint in legal_hints):
            score += 0.15
        
        # Check: formele structuur (lange paragrafen met nummering)
        numbered_lines = len(re.findall(r'^\s*\d+\.', sample, re.MULTILINE))
        if numbered_lines > 10:
            score += 0.1
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk juridische documenten op artikel-basis.
        
        Strategie:
        1. Detecteer artikelen (Art. 1, § 2, etc.)
        2. Per artikel: detecteer sub-artikelen/leden
        3. Chunk per artikel of sub-artikel
        4. Behoud volledige zinnen (nooit mid-sentence)
        5. GEEN overlap (juridische precisie)
        6. Extracteer metadata (artikelnummer, rechtsgebied, etc.)
        """
        split_subarticles = config.extra_params.get("split_subarticles", True)
        extract_metadata = config.extra_params.get("extract_metadata", True)
        
        # Stap 1: Split op hoofdartikelen
        articles = self._split_into_articles(text)
        
        if not articles:
            # Geen duidelijke artikel structuur, probeer paragraaf-based
            return self._fallback_paragraph_chunking(text, config)
        
        chunks: List[str] = []
        
        for article_num, article_title, article_content in articles:
            # Stap 2: Split artikel in sub-artikelen indien gewenst
            if split_subarticles and len(article_content) > config.max_chars:
                sub_chunks = self._split_article_into_subarticles(
                    article_num,
                    article_title,
                    article_content,
                    config
                )
                chunks.extend(sub_chunks)
            else:
                # Heel artikel als 1 chunk
                chunk = self._format_article_chunk(
                    article_num,
                    article_title,
                    article_content
                )
                chunks.append(chunk)
        
        # Metadata toevoegen indien gewenst
        if extract_metadata:
            chunks = self._add_legal_metadata(chunks, text)
        
        return chunks if chunks else [text.strip()]
    
    def _split_into_articles(self, text: str) -> List[Tuple[str, str, str]]:
        """
        Split document in artikelen.
        
        Returns:
            List van (article_number, article_title, article_content) tuples
        """
        articles = []
        
        # Probeer verschillende artikel patterns
        for pattern in self.ARTICLE_PATTERNS:
            matches = list(re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE))
            
            if len(matches) < 2:
                continue  # Te weinig artikelen, probeer ander pattern
            
            for i, match in enumerate(matches):
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                
                # Extract article header
                article_line_start = start
                article_line_end = text.find('\n', start)
                if article_line_end == -1:
                    article_line_end = start + 100
                
                article_header = text[article_line_start:article_line_end].strip()
                
                # Extract article number
                article_num = match.group(1) if len(match.groups()) > 0 else match.group(0)
                if len(match.groups()) > 1:
                    article_num = match.group(2)  # Voor "Artikel 1" patterns
                
                # Extract content
                content_start = article_line_end + 1 if article_line_end < len(text) else start
                content = text[content_start:end].strip()
                
                # Extract title (vaak na nummer op zelfde regel of volgende regel)
                title = ""
                header_parts = article_header.split(article_num, 1)
                if len(header_parts) > 1:
                    title = header_parts[1].strip().strip(':.-')
                
                articles.append((article_num, title, content))
            
            # Als we genoeg artikelen vonden, stop
            if articles:
                break
        
        return articles
    
    def _split_article_into_subarticles(
        self,
        article_num: str,
        article_title: str,
        content: str,
        config: ChunkingConfig
    ) -> List[str]:
        """
        Split een artikel in sub-artikelen/leden.
        """
        chunks = []
        
        # Probeer sub-artikel patterns
        sub_items = []
        for pattern in self.SUBARTICLE_PATTERNS:
            matches = list(re.finditer(pattern, content, re.MULTILINE))
            
            if len(matches) >= 2:
                # Gevonden! Split op deze pattern
                for i, match in enumerate(matches):
                    start = match.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                    
                    sub_num = match.group(1)
                    sub_content = content[start:end].strip()
                    sub_items.append((sub_num, sub_content))
                break
        
        if sub_items:
            # Maak chunks per sub-artikel
            for sub_num, sub_content in sub_items:
                chunk = self._format_subarticle_chunk(
                    article_num,
                    article_title,
                    sub_num,
                    sub_content
                )
                chunks.append(chunk)
        else:
            # Geen sub-artikelen gevonden, split op zinnen
            sentences = self._split_into_sentences(content)
            current_chunk = ""
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) <= config.max_chars:
                    current_chunk += sentence + " "
                else:
                    if current_chunk:
                        chunk = self._format_article_chunk(
                            article_num,
                            article_title,
                            current_chunk.strip()
                        )
                        chunks.append(chunk)
                    current_chunk = sentence + " "
            
            if current_chunk:
                chunk = self._format_article_chunk(
                    article_num,
                    article_title,
                    current_chunk.strip()
                )
                chunks.append(chunk)
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """
        Split tekst in volledige zinnen.
        Belangrijk voor juridische teksten: NOOIT mid-sentence splitsen.
        """
        # Split op zinseindes, maar behoud de punctuatie
        sentences = re.split(r'([.!?]+\s+)', text)
        
        result = []
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            result.append(sentence + punctuation)
        
        # Laatste deel (mogelijk zonder punctuatie)
        if len(sentences) % 2 == 1:
            result.append(sentences[-1])
        
        return [s.strip() for s in result if s.strip()]
    
    def _format_article_chunk(
        self,
        article_num: str,
        article_title: str,
        content: str
    ) -> str:
        """Format een artikel chunk met metadata markers."""
        parts = [f"[ARTIKEL {article_num}]"]
        
        if article_title:
            parts.append(f"[TITEL: {article_title}]")
        
        parts.append("")  # Lege regel
        parts.append(content)
        
        return "\n".join(parts)
    
    def _format_subarticle_chunk(
        self,
        article_num: str,
        article_title: str,
        sub_num: str,
        content: str
    ) -> str:
        """Format een sub-artikel chunk."""
        parts = [f"[ARTIKEL {article_num}.{sub_num}]"]
        
        if article_title:
            parts.append(f"[TITEL: {article_title}]")
        
        parts.append("")
        parts.append(content)
        
        return "\n".join(parts)
    
    def _fallback_paragraph_chunking(
        self,
        text: str,
        config: ChunkingConfig
    ) -> List[str]:
        """
        Fallback: als geen artikel structuur gevonden.
        Chunk op paragrafen maar behoud volledige zinnen.
        """
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        chunks = []
        current = ""
        
        for para in paragraphs:
            if len(current) + len(para) + 2 <= config.max_chars:
                current = f"{current}\n\n{para}" if current else para
            else:
                if current:
                    chunks.append(current)
                
                # Als paragraaf te lang, split op zinnen
                if len(para) > config.max_chars:
                    sentences = self._split_into_sentences(para)
                    sent_chunk = ""
                    for sent in sentences:
                        if len(sent_chunk) + len(sent) <= config.max_chars:
                            sent_chunk += sent + " "
                        else:
                            if sent_chunk:
                                chunks.append(sent_chunk.strip())
                            sent_chunk = sent + " "
                    current = sent_chunk.strip()
                else:
                    current = para
        
        if current:
            chunks.append(current)
        
        return chunks
    
    def _add_legal_metadata(self, chunks: List[str], original_text: str) -> List[str]:
        """
        Voeg juridische metadata toe aan chunks.
        
        Metadata:
        - Rechtsgebied (NL, EU, Gemeente, etc.)
        - Status (actief, vervallen, gewijzigd)
        - Geldigheidsdatum
        """
        # Detecteer rechtsgebied
        jurisdiction = None
        for pattern, juris in self.JURISDICTION_HINTS:
            if re.search(pattern, original_text, re.IGNORECASE):
                jurisdiction = juris
                break
        
        # Detecteer status
        status = "actief"  # default
        validity_date = None
        
        for pattern, detected_status in self.STATUS_PATTERNS:
            match = re.search(pattern, original_text, re.IGNORECASE)
            if match:
                status = detected_status
                # Probeer datum te extracten
                if len(match.groups()) > 1:
                    validity_date = match.group(2) if detected_status == 'gewijzigd' else match.group(1)
                break
        
        # Voor nu: voeg metadata niet direct toe aan chunk text
        # Deze kan later gebruikt worden bij indexing via een metadata dict
        # De markers [ARTIKEL X] zijn al voldoende voor referencing
        
        return chunks
