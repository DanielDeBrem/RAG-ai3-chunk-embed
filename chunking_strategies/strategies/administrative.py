"""
Administrative & Government Documents Chunking Strategy

Geoptimaliseerd voor ambtelijke en bestuurlijke documenten.
Focus op beleidsnota's, besluitstukken, subsidies en vergunningen.

Kenmerken:
- Sectie-gebaseerde chunking (Besluit, Motivatie, Voorwaarden, etc.)
- Samenvattende kop + alinea's
- Speciale secties apart chunken
- Metadata extractie (besluittype, bestuursorgaan, datum)
- Ondersteunt vage taal en veel verwijzingen

Belangrijk: Maakt vragen mogelijk als "kom ik in aanmerking als X en Y?"
"""
import re
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from ..base import ChunkStrategy, ChunkingConfig


class AdministrativeDocumentsStrategy(ChunkStrategy):
    """
    Chunking strategie voor ambtelijke en bestuurlijke documenten.
    
    Ondersteunt:
    - Beleidsnota's
    - Besluitstukken / raadsbesluiten
    - Subsidieregels en -aanvragen
    - Vergunningsdocumentatie
    - Ambtelijke adviezen
    - Collegebesluiten
    """
    
    name = "administrative"
    description = "Optimized for government documents: policy notes, decisions, grants, permits"
    default_config = {
        "max_chars": 1200,
        "overlap": 100,
        "extract_sections": True,
        "extract_metadata": True,
        "preserve_structure": True,
        "split_special_sections": True
    }
    
    # Speciale secties die apart gechunked moeten worden
    SPECIAL_SECTIONS = [
        r'(?i)(?:^|\n)\s*(BESLUIT|BESLISSING|BESCHIKKING)',
        r'(?i)(?:^|\n)\s*(MOTIVERING|OVERWEGINGEN?|TOELICHTING)',
        r'(?i)(?:^|\n)\s*(RANDVOORWAARDEN?|VOORWAARDEN?|BEPALINGEN)',
        r'(?i)(?:^|\n)\s*(UITSLUITINGEN?|NIET IN AANMERKING)',
        r'(?i)(?:^|\n)\s*(PROCEDURE|AANVRAAGPROCEDURE|STAPPEN)',
        r'(?i)(?:^|\n)\s*(TERMIJNEN?|DEADLINES?)',
    ]
    
    # Ambtelijke/bestuurlijke termen
    ADMINISTRATIVE_TERMS = [
        r'(?i)\b(college van b\s*&\s*w|burgemeester|wethouder)\b',
        r'(?i)\b(gemeenteraad|raadsbesluit|raadsvergadering)\b',
        r'(?i)\b(besluit|besluiten|beslissing|beschikking)\b',
        r'(?i)\b(subsidie|subsidieverlening|subsidiëren)\b',
        r'(?i)\b(vergunning|ontheffing|toestemming)\b',
        r'(?i)\b(beleid|beleidsplan|beleidsnota)\b',
        r'(?i)\b(advies|adviseert|geadviseerd)\b',
        r'(?i)\b(overwegende dat|gelet op|gezien)\b',
        r'(?i)\b(krachtens|ingevolge|op grond van)\b',
    ]
    
    # Subsidie/vergunning specifieke termen
    SUBSIDY_PERMIT_TERMS = [
        r'(?i)\b(in aanmerking|aanspraak|komen voor)\b',
        r'(?i)\b(voorwaarde|voldoen aan|vereist)\b',
        r'(?i)\b(uitgesloten|niet in aanmerking|afgewezen)\b',
        r'(?i)\b(aanvraag|indienen|aanvrager)\b',
        r'(?i)\b(termijn|uiterlijk|binnen.*dagen)\b',
        r'(?i)\b(budget|beschikbaar|maximaal bedrag)\b',
    ]
    
    # Bestuursorgaan patterns
    GOVERNMENT_BODY_PATTERNS = [
        (r'(?i)(gemeente\s+[\w\-]+)', 'gemeente'),
        (r'(?i)(college van b\s*&\s*w)', 'college'),
        (r'(?i)(gemeenteraad)', 'raad'),
        (r'(?i)(provincie\s+[\w\-]+)', 'provincie'),
        (r'(?i)(ministerie|minister van)', 'rijk'),
        (r'(?i)(waterschap)', 'waterschap'),
    ]
    
    # Besluittype patterns
    DECISION_TYPE_PATTERNS = [
        (r'(?i)(raadsbesluit)', 'raadsbesluit'),
        (r'(?i)(collegebesluit)', 'collegebesluit'),
        (r'(?i)(beschikking)', 'beschikking'),
        (r'(?i)(vergunning)', 'vergunning'),
        (r'(?i)(subsidieverlening|subsidietoekenning)', 'subsidie'),
        (r'(?i)(advies)', 'advies'),
        (r'(?i)(beleidsnota|beleidsplan)', 'beleid'),
    ]
    
    # Datum patterns
    DATE_PATTERNS = [
        r'(?:d\.?d\.?|datum|vastgesteld op)\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
        r'(\d{1,2}\s+(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\s+\d{4})',
    ]
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer ambtelijke/bestuurlijke documenten.
        
        Indicatoren:
        - Ambtelijk taalgebruik
        - Verwijzingen naar bestuursorganen
        - Besluit/motivatie structuur
        - Subsidie/vergunning termen
        - Formele datum vermeldingen
        """
        sample = text[:3000]
        metadata = metadata or {}
        
        score = 0.3  # Base score
        
        # Check: speciale secties
        special_section_count = sum(
            1 for pattern in self.SPECIAL_SECTIONS
            if re.search(pattern, sample, re.MULTILINE)
        )
        
        if special_section_count >= 2:
            score += 0.25
        elif special_section_count == 1:
            score += 0.15
        
        # Check: ambtelijke termen
        admin_term_count = sum(
            len(re.findall(pattern, sample))
            for pattern in self.ADMINISTRATIVE_TERMS
        )
        
        if admin_term_count >= 5:
            score += 0.20
        elif admin_term_count >= 3:
            score += 0.10
        
        # Check: subsidie/vergunning termen
        subsidy_term_count = sum(
            len(re.findall(pattern, sample))
            for pattern in self.SUBSIDY_PERMIT_TERMS
        )
        
        if subsidy_term_count >= 3:
            score += 0.15
        
        # Check: bestuursorgaan vermelding
        for pattern, _ in self.GOVERNMENT_BODY_PATTERNS:
            if re.search(pattern, sample):
                score += 0.15
                break
        
        # Check: datum patterns (formeel)
        date_matches = sum(
            len(re.findall(pattern, sample, re.IGNORECASE))
            for pattern in self.DATE_PATTERNS
        )
        if date_matches > 0:
            score += 0.10
        
        # Check: filename hints
        fn = metadata.get("filename", "").lower()
        admin_hints = [
            "besluit", "beleid", "nota", "subsidie", "vergunning",
            "raad", "college", "gemeente", "advies", "beschikking"
        ]
        if any(hint in fn for hint in admin_hints):
            score += 0.15
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk ambtelijke documenten met sectie-gebaseerde logica.
        
        Strategie:
        1. Detecteer speciale secties (Besluit, Motivatie, Voorwaarden, etc.)
        2. Chunk speciale secties apart
        3. Reguliere tekst: samenvattende kop + alinea's
        4. Extracteer metadata (besluittype, bestuursorgaan, datum)
        5. Behoud context voor "kom ik in aanmerking" vragen
        """
        split_special = config.extra_params.get("split_special_sections", True)
        extract_metadata = config.extra_params.get("extract_metadata", True)
        
        # Stap 1: Detecteer en split op speciale secties
        sections = self._split_into_sections(text)
        
        if not sections:
            # Geen duidelijke structuur, fallback
            return self._fallback_paragraph_chunking(text, config)
        
        chunks: List[str] = []
        
        for section_type, section_header, section_content in sections:
            if split_special and section_type in ['special', 'important']:
                # Speciale sectie: apart chunken (zelfs als klein)
                chunk = self._format_section_chunk(
                    section_type,
                    section_header,
                    section_content
                )
                chunks.append(chunk)
            else:
                # Reguliere sectie: split indien te lang
                if len(section_content) > config.max_chars:
                    sub_chunks = self._split_section_content(
                        section_header,
                        section_content,
                        config
                    )
                    chunks.extend(sub_chunks)
                else:
                    chunk = self._format_section_chunk(
                        section_type,
                        section_header,
                        section_content
                    )
                    chunks.append(chunk)
        
        # Metadata toevoegen
        if extract_metadata:
            chunks = self._add_administrative_metadata(chunks, text)
        
        return chunks if chunks else [text.strip()]
    
    def _split_into_sections(self, text: str) -> List[Tuple[str, str, str]]:
        """
        Split document in secties (speciale en reguliere).
        
        Returns:
            List van (section_type, section_header, section_content) tuples
            section_type: 'special', 'important', 'regular'
        """
        sections = []
        
        # Zoek alle sectie headers
        section_matches = []
        
        # Eerst speciale secties
        for pattern in self.SPECIAL_SECTIONS:
            for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
                section_matches.append((match.start(), match.group(0).strip(), 'special'))
        
        # Ook algemene headers (hoofdstuknummering, etc.)
        general_patterns = [
            r'(?m)^(\d+\.?\s+[A-Z][^\n]{5,60})$',  # 1. Inleiding
            r'(?m)^([A-Z][A-Z\s]{10,50})$',  # SAMENVATTING
        ]
        
        for pattern in general_patterns:
            for match in re.finditer(pattern, text):
                # Check of dit niet al een special section is
                start = match.start()
                if not any(abs(start - sm[0]) < 10 for sm in section_matches):
                    section_matches.append((start, match.group(1).strip(), 'regular'))
        
        # Sort op positie
        section_matches.sort(key=lambda x: x[0])
        
        if not section_matches:
            return [('regular', '', text)]
        
        # Bouw secties
        for i, (pos, header, section_type) in enumerate(section_matches):
            next_pos = section_matches[i + 1][0] if i + 1 < len(section_matches) else len(text)
            
            # Extract content (skip header zelf)
            content_start = pos + len(header)
            content = text[content_start:next_pos].strip()
            
            sections.append((section_type, header, content))
        
        # Voeg preamble toe als die er is
        if section_matches[0][0] > 50:
            preamble = text[:section_matches[0][0]].strip()
            if preamble:
                sections.insert(0, ('important', 'Inleiding', preamble))
        
        return sections
    
    def _split_section_content(
        self,
        section_header: str,
        content: str,
        config: ChunkingConfig
    ) -> List[str]:
        """Split lange sectie content in chunks."""
        chunks = []
        
        # Split op alinea's
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        current = ""
        for para in paragraphs:
            potential = f"{current}\n\n{para}" if current else para
            
            if len(potential) <= config.max_chars:
                current = potential
            else:
                if current:
                    chunk = self._format_section_chunk(
                        'regular',
                        section_header,
                        current
                    )
                    chunks.append(chunk)
                
                # Overlap toevoegen
                if config.overlap > 0 and len(current) > config.overlap:
                    current = current[-config.overlap:] + "\n\n" + para
                else:
                    current = para
        
        if current:
            chunk = self._format_section_chunk(
                'regular',
                section_header,
                current
            )
            chunks.append(chunk)
        
        return chunks
    
    def _format_section_chunk(
        self,
        section_type: str,
        section_header: str,
        content: str
    ) -> str:
        """Format een sectie chunk met markers."""
        parts = []
        
        # Marker voor sectie type
        if section_type == 'special':
            parts.append(f"[SECTIE: {section_header}]")
            parts.append("[TYPE: BELANGRIJK]")
        elif section_type == 'important':
            parts.append(f"[SECTIE: {section_header}]")
        else:
            if section_header:
                parts.append(f"[{section_header}]")
        
        parts.append("")  # Lege regel
        parts.append(content)
        
        return "\n".join(parts)
    
    def _fallback_paragraph_chunking(
        self,
        text: str,
        config: ChunkingConfig
    ) -> List[str]:
        """Fallback: reguliere paragraaf chunking."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        if not paragraphs:
            return [text.strip()] if text.strip() else []
        
        chunks = []
        current = ""
        
        for para in paragraphs:
            potential = f"{current}\n\n{para}" if current else para
            
            if len(potential) <= config.max_chars:
                current = potential
            else:
                if current:
                    chunks.append(current)
                
                if config.overlap > 0 and len(current) > config.overlap:
                    current = current[-config.overlap:] + "\n\n" + para
                else:
                    current = para
        
        if current:
            chunks.append(current)
        
        return chunks
    
    def _add_administrative_metadata(
        self,
        chunks: List[str],
        original_text: str
    ) -> List[str]:
        """
        Voeg ambtelijke metadata toe.
        
        Metadata:
        - Besluittype (raadsbesluit, vergunning, etc.)
        - Bestuursorgaan (gemeente, college, etc.)
        - Datum
        """
        # Detecteer besluittype
        decision_type = None
        for pattern, dtype in self.DECISION_TYPE_PATTERNS:
            if re.search(pattern, original_text, re.IGNORECASE):
                decision_type = dtype
                break
        
        # Detecteer bestuursorgaan
        government_body = None
        for pattern, body in self.GOVERNMENT_BODY_PATTERNS:
            match = re.search(pattern, original_text, re.IGNORECASE)
            if match:
                government_body = match.group(1)
                break
        
        # Detecteer datum
        document_date = None
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, original_text, re.IGNORECASE)
            if match:
                document_date = match.group(1)
                break
        
        # Voor nu: metadata markers zijn al voldoende
        # De [SECTIE: X] en [TYPE: BELANGRIJK] markers helpen bij retrieval
        
        return chunks
