"""
Base Classes for Modular Chunking Strategies

Definieert de interface en base classes voor alle chunking strategieën.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


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
