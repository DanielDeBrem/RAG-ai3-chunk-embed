"""
Financial Tables & Numbers Chunking Strategy

Geoptimaliseerd voor financiële documenten met tabellen en cijfers.
Focus op jaarrekeningen, financiële rapportages, offertes en prijslijsten.

Kenmerken:
- Hybride chunking per sectie (Balans, V&W, Kasstroom, Toelichting)
- Tabellen: rij-per-rij én kolom-per-kolom voor tijdreeksen
- KPI-tracking over meerdere jaren
- Metadata extractie (jaar, entiteit, KPI-type)
- Prijstabellen regel-per-regel
"""
import re
from typing import List, Optional, Dict, Any, Tuple
from ..base import ChunkStrategy, ChunkingConfig


class FinancialTablesStrategy(ChunkStrategy):
    """
    Chunking strategie voor financiële documenten met tabellen.
    
    Ondersteunt:
    - Jaarrekeningen (balans, V&W, kasstroom)
    - Financiële rapportages
    - Offertes & prijsopgaven
    - Contractvoorstellen
    """
    
    name = "financial_tables"
    description = "Optimized for financial documents with tables and numbers (annual reports, quotes, contracts)"
    default_config = {
        "max_chars": 1500,
        "overlap": 100,
        "table_mode": "hybrid",  # "row", "column", "hybrid"
        "extract_metadata": True,
        "preserve_section_headers": True,
        "split_large_tables": True
    }
    
    # Sectie patterns voor financiële documenten
    FINANCIAL_SECTIONS = [
        r"(?i)(balans|balance\s+sheet)",
        r"(?i)(resultatenrekening|winst[- ]en[- ]verlies|profit\s+and\s+loss|p&l|v&w)",
        r"(?i)(kasstroom|cashflow|cash\s+flow)",
        r"(?i)(toelichting|notes?|verklarende)",
        r"(?i)(waardering|valuation)",
        r"(?i)(eigen\s+vermogen|equity)",
        r"(?i)(bezittingen|assets|activa)",
        r"(?i)(schulden|liabilities|passiva)",
    ]
    
    # Offerte/contract sectie patterns
    CONTRACT_SECTIONS = [
        r"(?i)(scope|omvang|werkzaamheden)",
        r"(?i)(prijs|price|bedrag|tarief|kosten)",
        r"(?i)(looptijd|duration|termijn)",
        r"(?i)(levering|delivery|voorwaarden)",
        r"(?i)(betalings?voorwaarden|payment\s+terms)",
        r"(?i)(garantie|warranty)",
    ]
    
    # KPI patterns
    KPI_PATTERNS = [
        r"(?i)(omzet|revenue|turnover)",
        r"(?i)(ebitda|ebit)",
        r"(?i)(winst|profit|result[aat]?)",
        r"(?i)(marge|margin)",
        r"(?i)(kosten|costs|expenses)",
        r"(?i)(activa|assets|bezittingen)",
        r"(?i)(passiva|liabilities|schulden)",
        r"(?i)(eigen\s+vermogen|equity)",
        r"(?i)(liquiditeit|liquidity|solvabiliteit)",
    ]
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer financiële documenten met tabellen.
        
        Indicatoren:
        - Financiële termen (balans, V&W, EBITDA)
        - Tabel structuren
        - Jaartallen en bedragen
        - Valuta symbolen
        - Sectie headers
        """
        sample = text[:3000]  # Grotere sample voor financiële docs
        metadata = metadata or {}
        
        score = 0.3  # Base score
        
        # Check: financiële sectie headers
        financial_section_count = 0
        for pattern in self.FINANCIAL_SECTIONS:
            if re.search(pattern, sample):
                financial_section_count += 1
        
        if financial_section_count >= 2:
            score += 0.3
        elif financial_section_count == 1:
            score += 0.15
        
        # Check: contract/offerte termen
        contract_section_count = 0
        for pattern in self.CONTRACT_SECTIONS:
            if re.search(pattern, sample):
                contract_section_count += 1
        
        if contract_section_count >= 2:
            score += 0.2
        
        # Check: KPI termen
        kpi_count = sum(1 for pattern in self.KPI_PATTERNS if re.search(pattern, sample))
        if kpi_count >= 3:
            score += 0.2
        
        # Check: tabel structuren
        table_indicators = [
            len(re.findall(r'\|.*\|.*\|', sample)),  # Pipe tables
            len(re.findall(r'\t.*\t', sample)),  # Tab-separated
            len(re.findall(r'^\s*[-+|]+\s*$', sample, re.MULTILINE)),  # Table borders
        ]
        if any(count > 3 for count in table_indicators):
            score += 0.2
        
        # Check: getallen en valuta
        numbers_with_decimals = len(re.findall(r'\d+[.,]\d{2,}', sample))
        currency_symbols = len(re.findall(r'[€$£]\s*\d+|EUR|USD', sample))
        
        if numbers_with_decimals > 10 or currency_symbols > 5:
            score += 0.15
        
        # Check: jaartallen (meerdere jaren = tijdreeks)
        years = re.findall(r'\b(19|20)\d{2}\b', sample)
        unique_years = len(set(years))
        if unique_years >= 2:
            score += 0.15
        
        # Check: filename hints
        fn = metadata.get("filename", "").lower()
        financial_hints = [
            "jaarrekening", "annual", "financial", "financieel",
            "balans", "resultaat", "offerte", "quote", "contract",
            "prijslijst", "tarief", "kosten", "taxatie"
        ]
        if any(hint in fn for hint in financial_hints):
            score += 0.15
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk financiële documenten met intelligente tabel handling.
        
        Strategie:
        1. Detecteer hoofdsecties (Balans, V&W, etc.)
        2. Per sectie: identificeer tabellen
        3. Tabellen: chunk rij-per-rij met context
        4. Niet-tabel tekst: reguliere chunking
        5. Extracteer metadata waar mogelijk
        """
        table_mode = config.extra_params.get("table_mode", "hybrid")
        extract_metadata = config.extra_params.get("extract_metadata", True)
        preserve_headers = config.extra_params.get("preserve_section_headers", True)
        
        # Stap 1: Detecteer secties
        sections = self._split_into_sections(text)
        
        chunks: List[str] = []
        
        for section_header, section_content in sections:
            # Stap 2: Detecteer tabellen binnen sectie
            parts = self._extract_tables_from_section(section_content)
            
            for part_type, part_content in parts:
                if part_type == "table":
                    # Tabel chunking
                    table_chunks = self._chunk_table(
                        part_content,
                        section_header,
                        table_mode,
                        config
                    )
                    chunks.extend(table_chunks)
                else:
                    # Reguliere tekst
                    if preserve_headers and section_header:
                        text_with_header = f"[{section_header}]\n\n{part_content}"
                    else:
                        text_with_header = part_content
                    
                    # Split lange tekst
                    if len(text_with_header) > config.max_chars:
                        sub_chunks = self._chunk_text_part(text_with_header, config)
                        chunks.extend(sub_chunks)
                    else:
                        chunks.append(text_with_header)
        
        # Als geen secties gevonden, fallback
        if not chunks:
            chunks = self._chunk_text_part(text, config)
        
        # Metadata extractie
        if extract_metadata:
            chunks = self._add_metadata_to_chunks(chunks, text)
        
        return chunks
    
    def _split_into_sections(self, text: str) -> List[Tuple[str, str]]:
        """
        Split document in hoofdsecties (Balans, V&W, etc.).
        
        Returns:
            List van (section_header, section_content) tuples
        """
        # Zoek alle section headers
        all_patterns = self.FINANCIAL_SECTIONS + self.CONTRACT_SECTIONS
        
        section_matches = []
        for pattern in all_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                # Pak de hele regel als header
                start = match.start()
                line_start = text.rfind('\n', 0, start) + 1
                line_end = text.find('\n', start)
                if line_end == -1:
                    line_end = len(text)
                
                header = text[line_start:line_end].strip()
                section_matches.append((match.start(), header))
        
        # Sort op positie en verwijder duplicates
        section_matches.sort(key=lambda x: x[0])
        
        if not section_matches:
            return [("", text)]
        
        # Bouw secties
        sections = []
        for i, (pos, header) in enumerate(section_matches):
            next_pos = section_matches[i + 1][0] if i + 1 < len(section_matches) else len(text)
            content = text[pos:next_pos].strip()
            # Verwijder header uit content
            content = content[len(header):].strip()
            sections.append((header, content))
        
        # Voeg content voor eerste sectie toe als die er is
        if section_matches[0][0] > 0:
            preamble = text[:section_matches[0][0]].strip()
            if preamble:
                sections.insert(0, ("Inleiding", preamble))
        
        return sections
    
    def _extract_tables_from_section(self, text: str) -> List[Tuple[str, str]]:
        """
        Identificeer tabellen vs. reguliere tekst in een sectie.
        
        Returns:
            List van ("table"|"text", content) tuples
        """
        lines = text.split('\n')
        parts = []
        current_type = None
        current_content = []
        
        for line in lines:
            # Detecteer of dit een tabel regel is
            is_table_line = self._is_table_line(line)
            
            if is_table_line:
                if current_type != "table":
                    # Sla vorige tekst op
                    if current_content:
                        parts.append((current_type or "text", '\n'.join(current_content)))
                    current_type = "table"
                    current_content = [line]
                else:
                    current_content.append(line)
            else:
                if current_type == "table":
                    # Einde van tabel
                    parts.append(("table", '\n'.join(current_content)))
                    current_type = "text"
                    current_content = [line]
                else:
                    if not current_type:
                        current_type = "text"
                    current_content.append(line)
        
        # Laatste part toevoegen
        if current_content:
            parts.append((current_type or "text", '\n'.join(current_content)))
        
        return parts
    
    def _is_table_line(self, line: str) -> bool:
        """Check of een regel deel is van een tabel."""
        # Pipe tables
        if re.match(r'^\s*\|.*\|.*\|', line):
            return True
        
        # Tab-separated (minimaal 2 tabs)
        if line.count('\t') >= 2:
            return True
        
        # Table borders
        if re.match(r'^\s*[-+=|]+\s*$', line):
            return True
        
        # Getallen in kolommen (heuristiek)
        # Minimaal 3 getallen gescheiden door spaties
        numbers = re.findall(r'\b\d+[.,]?\d*\b', line)
        if len(numbers) >= 3 and len(line.strip()) < 200:
            return True
        
        return False
    
    def _chunk_table(
        self,
        table_text: str,
        section_header: str,
        mode: str,
        config: ChunkingConfig
    ) -> List[str]:
        """
        Chunk een tabel in betekenisvolle eenheden.
        
        Modes:
        - "row": 1 rij = 1 chunk (met header)
        - "column": Kolommen over tijd
        - "hybrid": Intelligent kiezen
        """
        lines = [l for l in table_text.split('\n') if l.strip()]
        
        if not lines:
            return []
        
        # Detecteer header rij (vaak eerste niet-border regel)
        header_idx = 0
        for i, line in enumerate(lines):
            if not re.match(r'^\s*[-+=|]+\s*$', line):
                header_idx = i
                break
        
        header = lines[header_idx] if header_idx < len(lines) else ""
        data_lines = [l for l in lines[header_idx + 1:] 
                      if not re.match(r'^\s*[-+=|]+\s*$', l)]
        
        # Context prefix
        context = f"[{section_header}]\n" if section_header else ""
        context += "[TABEL]\n"
        
        chunks = []
        
        if mode == "row" or (mode == "hybrid" and len(data_lines) <= 20):
            # Rij-per-rij chunking
            for row in data_lines:
                chunk = f"{context}{header}\n{row}"
                chunks.append(chunk)
        
        elif mode == "column" or (mode == "hybrid" and len(data_lines) > 20):
            # Kolom chunking (voor tijdreeksen)
            # Parse tabel structuur
            parsed = self._parse_table_structure(header, data_lines)
            
            if parsed:
                # Maak chunks per KPI over alle jaren
                for kpi, values in parsed.items():
                    chunk = f"{context}KPI: {kpi}\n"
                    chunk += "\n".join(f"{year}: {val}" for year, val in values.items())
                    chunks.append(chunk)
            else:
                # Fallback naar row mode
                for row in data_lines[:10]:  # Limiteer aantal
                    chunk = f"{context}{header}\n{row}"
                    chunks.append(chunk)
        
        return chunks if chunks else [f"{context}{table_text}"]
    
    def _parse_table_structure(self, header: str, rows: List[str]) -> Optional[Dict[str, Dict[str, str]]]:
        """
        Parse tabel in KPI -> {jaar: waarde} structuur.
        
        Heuristiek voor financiële tabellen met tijdreeksen.
        """
        # Detecteer kolommen in header (simpel: split op | of tabs)
        if '|' in header:
            cols = [c.strip() for c in header.split('|') if c.strip()]
        elif '\t' in header:
            cols = [c.strip() for c in header.split('\t') if c.strip()]
        else:
            # Moeilijker: split op multiple spaces
            cols = [c.strip() for c in re.split(r'\s{2,}', header) if c.strip()]
        
        # Check of kolommen jaartallen zijn
        year_cols = []
        for col in cols[1:]:  # Skip eerste kolom (meestal label)
            year_match = re.search(r'\b(19|20)\d{2}\b', col)
            if year_match:
                year_cols.append(year_match.group())
        
        if not year_cols:
            return None
        
        # Parse rows
        result = {}
        for row in rows[:50]:  # Limiteer aantal rijen
            if '|' in row:
                cells = [c.strip() for c in row.split('|') if c.strip()]
            elif '\t' in row:
                cells = [c.strip() for c in row.split('\t') if c.strip()]
            else:
                cells = [c.strip() for c in re.split(r'\s{2,}', row) if c.strip()]
            
            if len(cells) < 2:
                continue
            
            kpi_name = cells[0]
            values = cells[1:len(year_cols) + 1]
            
            if kpi_name and values:
                result[kpi_name] = {
                    year: val for year, val in zip(year_cols, values) if val
                }
        
        return result if result else None
    
    def _chunk_text_part(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk niet-tabel tekst (fallback naar paragraph splitting)."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        if not paragraphs:
            return [text.strip()] if text.strip() else []
        
        chunks = []
        current = ""
        
        for para in paragraphs:
            if len(current) + len(para) + 2 <= config.max_chars:
                current = f"{current}\n\n{para}" if current else para
            else:
                if current:
                    chunks.append(current)
                current = para
        
        if current:
            chunks.append(current)
        
        return chunks
    
    def _add_metadata_to_chunks(self, chunks: List[str], original_text: str) -> List[str]:
        """
        Voeg metadata toe aan chunks (als markers).
        
        Metadata kan later geëxtraheerd worden bij indexing.
        """
        # Detecteer jaren in document
        years = set(re.findall(r'\b(19|20)\d{2}\b', original_text))
        
        # Detecteer entiteit (BV/NV naam)
        entity_match = re.search(r'([A-Z][a-zA-Z\s&]+(?:B\.?V\.?|N\.?V\.?))', original_text)
        entity = entity_match.group(1) if entity_match else None
        
        # Voor nu: voeg niet toe aan chunks zelf (zou parsing bemoeilijken)
        # Maar return metadata als dit later nodig is via een andere interface
        
        return chunks
