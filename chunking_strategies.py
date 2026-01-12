"""
Modular Chunking Strategies System

Pluggable chunking strategieën die eenvoudig kunnen worden toegevoegd,
aangepast of verwijderd zonder de main application code te raken.
"""
import re
import logging
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ChunkingConfig:
    """Configuration for a chunking strategy."""
    max_chars: int = 800
    overlap: int = 0
    extra_params: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra_params is None:
            self.extra_params = {}


class ChunkStrategy(ABC):
    """
    Base class voor alle chunking strategieën.
    
    Elke strategie moet implementeren:
    - name: Unieke naam
    - description: Wat doet deze strategie
    - default_config: Default configuratie
    - detect_applicability(): Hoe goed past deze strategie bij de data
    - chunk(): Daadwerkelijke chunking logica
    """
    
    name: str = "base"
    description: str = ""
    default_config: Dict[str, Any] = {}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Bepaal hoe goed deze strategie past bij de gegeven data.
        
        Args:
            text: De te chunken tekst (eerste 2000 chars voor snelheid)
            metadata: Extra metadata (filename, mime_type, etc.)
            
        Returns:
            Confidence score tussen 0.0 en 1.0
            - 0.0 = absoluut niet geschikt
            - 0.5 = mogelijk geschikt
            - 1.0 = perfect geschikt
        """
        return 0.0
    
    @abstractmethod
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Voer de chunking uit.
        
        Args:
            text: Volledige tekst om te chunken
            config: Chunking configuratie
            
        Returns:
            Lijst van chunks
        """
        raise NotImplementedError
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Valideer of de config parameters geldig zijn."""
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Return info over deze strategie."""
        return {
            "name": self.name,
            "description": self.description,
            "default_config": self.default_config,
        }


# ============================================================================
# Concrete Strategy Implementations
# ============================================================================

class DefaultStrategy(ChunkStrategy):
    """Standaard paragraph-based chunking."""
    
    name = "default"
    description = "Standard paragraph-based chunking with optional overlap"
    default_config = {"max_chars": 800, "overlap": 0}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        # Default strategie: altijd bruikbaar maar lage prioriteit
        return 0.3
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk op paragrafen met optionele overlap."""
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: List[str] = []
        buf = ""
        
        for p in paras:
            if len(buf) + len(p) + 2 <= config.max_chars:
                buf = f"{buf}\n\n{p}" if buf else p
            else:
                if buf:
                    chunks.append(buf)
                    # Overlap: neem laatste deel mee
                    if config.overlap > 0 and len(buf) > config.overlap:
                        buf = buf[-config.overlap:] + "\n\n" + p
                    else:
                        buf = p
                else:
                    buf = p
        
        if buf:
            chunks.append(buf)
        if not chunks and text.strip():
            chunks = [text.strip()]
        
        return chunks


class PageAwareStrategy(ChunkStrategy):
    """PDF's met pagina grenzen en tabellen."""
    
    name = "page_plus_table_aware"
    description = "Respects page boundaries ([PAGE X]) and preserves tables (for PDFs)"
    default_config = {"max_chars": 1500, "overlap": 200}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        sample = text[:2000]
        metadata = metadata or {}
        
        # Hoge score als PAGE markers gevonden
        if "[PAGE" in sample:
            return 0.95
        
        # Medium score voor PDF's
        if metadata.get("mime_type") == "application/pdf":
            return 0.70
        
        if metadata.get("filename", "").lower().endswith(".pdf"):
            return 0.70
        
        return 0.1
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk op pagina grenzen."""
        # Zoek pagina markers
        pages = re.split(r'\[PAGE \d+\]', text)
        pages = [p.strip() for p in pages if p.strip()]
        
        if not pages:
            # Fallback naar default
            return DefaultStrategy().chunk(text, config)
        
        chunks: List[str] = []
        for i, page in enumerate(pages):
            page_header = f"[PAGE {i+1}]\n"
            
            # Als pagina te lang is, split verder
            if len(page) > config.max_chars:
                # Gebruik default chunking voor lange pagina's
                sub_chunks = DefaultStrategy().chunk(
                    page, 
                    ChunkingConfig(max_chars=config.max_chars - len(page_header), overlap=config.overlap)
                )
                for sc in sub_chunks:
                    chunks.append(page_header + sc)
            else:
                chunks.append(page_header + page)
        
        return chunks


class SemanticSectionsStrategy(ChunkStrategy):
    """Chunk op headers en secties (Markdown-style)."""
    
    name = "semantic_sections"
    description = "Splits on headers and sections (# ## ### or === ---)"
    default_config = {"max_chars": 1200, "overlap": 150}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        sample = text[:2000]
        metadata = metadata or {}
        
        # Detecteer Markdown headers
        md_headers = len(re.findall(r'(?m)^#{1,3}\s+.+$', sample))
        if md_headers > 2:
            return 0.85
        
        # Detecteer underline headers
        underline_headers = len(re.findall(r'(?m)^.+\n[=-]{3,}$', sample))
        if underline_headers > 1:
            return 0.80
        
        # Check filename
        fn = metadata.get("filename", "").lower()
        if fn.endswith((".md", ".markdown")):
            return 0.75
        
        return 0.2
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk op headers/secties."""
        # Split op headers
        sections = re.split(r'(?m)^(#{1,3}\s+.+|.+\n[=-]{3,})$', text)
        sections = [s.strip() for s in sections if s.strip()]
        
        if len(sections) <= 1:
            return DefaultStrategy().chunk(text, config)
        
        chunks: List[str] = []
        current_header = ""
        
        for section in sections:
            # Check of dit een header is
            is_header = (re.match(r'^#{1,3}\s+', section) or 
                        re.match(r'.+\n[=-]{3,}$', section))
            
            if is_header:
                current_header = section + "\n\n"
            else:
                full_section = current_header + section
                if len(full_section) > config.max_chars:
                    sub_chunks = DefaultStrategy().chunk(full_section, config)
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(full_section)
        
        return chunks if chunks else DefaultStrategy().chunk(text, config)


class ConversationStrategy(ChunkStrategy):
    """Chunk per conversatie turn (chatlogs, messaging)."""
    
    name = "conversation_turns"
    description = "Splits on conversation turns (User:, Assistant:, Q:, etc.)"
    default_config = {"max_chars": 600, "overlap": 0}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        sample = text[:2000]
        metadata = metadata or {}
        
        # Detecteer conversatie patterns
        pattern = r'(?:User|Assistant|Client|Therapist|Coach|Coachee|Q|A|Vraag|Antwoord)\s*:'
        matches = len(re.findall(pattern, sample, re.IGNORECASE))
        
        if matches > 5:
            return 0.90
        elif matches > 2:
            return 0.75
        
        # Check filename hints
        fn = metadata.get("filename", "").lower()
        if any(word in fn for word in ["chat", "conversation", "whatsapp", "telegram", "slack"]):
            return 0.85
        
        return 0.1
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk per conversatie turn."""
        # Split op speaker patterns
        pattern = r'(?m)^((?:User|Assistant|Client|Therapist|Coach|Coachee|Q|A|Vraag|Antwoord)\s*:)'
        turns = re.split(pattern, text, flags=re.IGNORECASE)
        
        if len(turns) <= 1:
            return DefaultStrategy().chunk(text, config)
        
        chunks: List[str] = []
        current_turn = ""
        
        for i, part in enumerate(turns):
            if re.match(pattern, part, re.IGNORECASE):
                if current_turn:
                    chunks.append(current_turn.strip())
                current_turn = part
            else:
                current_turn += part
        
        if current_turn:
            chunks.append(current_turn.strip())
        
        # Combineer kleine turns tot max_chars
        merged: List[str] = []
        buf = ""
        for c in chunks:
            if len(buf) + len(c) + 2 <= config.max_chars:
                buf = f"{buf}\n\n{c}" if buf else c
            else:
                if buf:
                    merged.append(buf)
                buf = c
        if buf:
            merged.append(buf)
        
        return merged if merged else chunks


class TableAwareStrategy(ChunkStrategy):
    """Preserve table structures."""
    
    name = "table_aware"
    description = "Preserves table structures (| col | or tabs)"
    default_config = {"max_chars": 1000, "overlap": 100}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        sample = text[:2000]
        
        # Detecteer tabel patterns
        table_lines = len(re.findall(r'^[\|\+\-].*[\|\+\-]$', sample, re.MULTILINE))
        tab_lines = sum(1 for line in sample.split('\n') if line.count('\t') >= 2)
        
        if table_lines > 3 or tab_lines > 3:
            return 0.85
        
        return 0.2
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """Chunk met tabel-preservatie."""
        lines = text.split('\n')
        chunks: List[str] = []
        current_chunk: List[str] = []
        in_table = False
        table_buffer: List[str] = []
        
        for line in lines:
            is_table_line = bool(re.match(r'^[\|\+\-].*[\|\+\-]$', line.strip()) or 
                                '\t' in line and line.count('\t') >= 2)
            
            if is_table_line:
                if not in_table and current_chunk:
                    # Start nieuwe tabel
                    chunk_text = '\n'.join(current_chunk)
                    if chunk_text.strip():
                        chunks.append(chunk_text)
                    current_chunk = []
                in_table = True
                table_buffer.append(line)
            else:
                if in_table and table_buffer:
                    # Einde van tabel
                    table_text = '\n'.join(table_buffer)
                    chunks.append(f"[TABLE]\n{table_text}")
                    table_buffer = []
                    in_table = False
                
                current_chunk.append(line)
                
                # Check lengte
                if len('\n'.join(current_chunk)) > config.max_chars:
                    chunk_text = '\n'.join(current_chunk[:-1])
                    if chunk_text.strip():
                        chunks.append(chunk_text)
                    current_chunk = [current_chunk[-1]] if config.overlap > 0 else []
        
        # Restanten
        if table_buffer:
            chunks.append(f"[TABLE]\n{'\n'.join(table_buffer)}")
        if current_chunk:
            chunk_text = '\n'.join(current_chunk)
            if chunk_text.strip():
                chunks.append(chunk_text)
        
        return chunks if chunks else DefaultStrategy().chunk(text, config)


# ============================================================================
# Strategy Registry
# ============================================================================

class ChunkStrategyRegistry:
    """Centraal register voor alle chunking strategieën."""
    
    def __init__(self):
        self.strategies: Dict[str, ChunkStrategy] = {}
        self._register_default_strategies()
    
    def _register_default_strategies(self):
        """Registreer alle built-in strategieën."""
        for strategy_class in [
            DefaultStrategy,
            PageAwareStrategy,
            SemanticSectionsStrategy,
            ConversationStrategy,
            TableAwareStrategy,
        ]:
            self.register(strategy_class())
    
    def register(self, strategy: ChunkStrategy):
        """Registreer een nieuwe strategie."""
        self.strategies[strategy.name] = strategy
        logger.info(f"Registered chunking strategy: {strategy.name}")
    
    def get(self, name: str) -> Optional[ChunkStrategy]:
        """Haal strategie op bij naam."""
        return self.strategies.get(name)
    
    def list_available(self) -> List[Dict[str, Any]]:
        """Lijst alle beschikbare strategieën."""
        return [strategy.get_info() for strategy in self.strategies.values()]
    
    def auto_detect(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Detecteer beste strategie voor deze data.
        
        Returns:
            Naam van de strategie met hoogste confidence
        """
        if not text:
            return "default"
        
        # Gebruik eerste 2000 chars voor detectie (snelheid)
        sample = text[:2000]
        
        scores = {}
        for name, strategy in self.strategies.items():
            try:
                score = strategy.detect_applicability(sample, metadata)
                scores[name] = score
                logger.debug(f"Strategy '{name}' applicability: {score:.2f}")
            except Exception as e:
                logger.warning(f"Error detecting applicability for '{name}': {e}")
                scores[name] = 0.0
        
        best_strategy = max(scores, key=scores.get)
        logger.info(f"Auto-detected chunking strategy: {best_strategy} (score: {scores[best_strategy]:.2f})")
        
        return best_strategy
    
    def chunk_text(
        self, 
        text: str, 
        strategy_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Chunk text met opgegeven of auto-detected strategie.
        
        Args:
            text: Te chunken tekst
            strategy_name: Strategie naam (None = auto-detect)
            config: Custom config (None = use defaults)
            metadata: Extra metadata voor auto-detection
            
        Returns:
            Lijst van chunks
        """
        # Auto-detect als geen strategie opgegeven
        if not strategy_name:
            strategy_name = self.auto_detect(text, metadata)
        
        # Haal strategie op
        strategy = self.get(strategy_name)
        if not strategy:
            logger.warning(f"Strategy '{strategy_name}' not found, using default")
            strategy = self.get("default")
        
        # Merge config met defaults
        final_config = {**strategy.default_config}
        if config:
            final_config.update(config)
        
        chunking_config = ChunkingConfig(
            max_chars=final_config.get("max_chars", 800),
            overlap=final_config.get("overlap", 0),
            extra_params=final_config
        )
        
        # Chunk!
        try:
            chunks = strategy.chunk(text, chunking_config)
            logger.info(f"Chunked with '{strategy_name}': {len(chunks)} chunks created")
            return chunks
        except Exception as e:
            logger.error(f"Chunking failed with '{strategy_name}': {e}, falling back to default")
            return DefaultStrategy().chunk(text, chunking_config)


# Global registry instance
_registry = None


def get_registry() -> ChunkStrategyRegistry:
    """Get global registry instance (singleton)."""
    global _registry
    if _registry is None:
        _registry = ChunkStrategyRegistry()
    return _registry


# Convenience functions
def chunk_text(
    text: str,
    strategy: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Convenience function to chunk text."""
    return get_registry().chunk_text(text, strategy, config, metadata)


def list_strategies() -> List[Dict[str, Any]]:
    """List all available strategies."""
    return get_registry().list_available()


def detect_strategy(text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Auto-detect best strategy."""
    return get_registry().auto_detect(text, metadata)
