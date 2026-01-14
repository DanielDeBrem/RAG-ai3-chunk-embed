"""
Modular Chunking Strategies System

Pluggable chunking strategieën die eenvoudig kunnen worden toegevoegd,
aangepast of verwijderd zonder de main application code te raken.

Usage:
    from chunking_strategies import chunk_text, list_strategies, detect_strategy
    
    # Automatisch beste strategie kiezen
    chunks = chunk_text("your text here")
    
    # Specifieke strategie gebruiken
    chunks = chunk_text("your text", strategy="free_text")
    
    # Met custom config
    chunks = chunk_text("your text", config={"max_chars": 1200, "overlap": 200})
    
    # Lijst beschikbare strategieën
    strategies = list_strategies()
"""
import logging
from typing import List, Dict, Any, Optional

# Import base classes
from .base import ChunkStrategy, ChunkingConfig

# Import registry
from .registry import (
    ChunkStrategyRegistry,
    get_registry,
    chunk_text,
    list_strategies,
    detect_strategy
)

# Import all strategies
from .strategies import (
    DefaultStrategy, 
    FreeTextStrategy, 
    FinancialTablesStrategy, 
    LegalDocumentsStrategy,
    AdministrativeDocumentsStrategy,
    ReviewsStrategy,
    MenusStrategy
)

logger = logging.getLogger(__name__)


def _initialize_default_strategies():
    """
    Registreer alle standaard strategieën bij import.
    Dit zorgt ervoor dat de strategieën direct beschikbaar zijn.
    """
    registry = get_registry()
    
    # Registreer default strategies
    strategies_to_register = [
        DefaultStrategy(),
        FreeTextStrategy(),
        FinancialTablesStrategy(),
        LegalDocumentsStrategy(),
        AdministrativeDocumentsStrategy(),
        ReviewsStrategy(),
        MenusStrategy(),
    ]
    
    for strategy in strategies_to_register:
        try:
            registry.register(strategy)
        except Exception as e:
            logger.error(f"Failed to register strategy '{strategy.name}': {e}")


# Auto-initialize bij import
_initialize_default_strategies()


# Export public API
__all__ = [
    # Base classes (voor custom strategies)
    "ChunkStrategy",
    "ChunkingConfig",
    
    # Registry
    "ChunkStrategyRegistry",
    "get_registry",
    
    # Convenience functions (most common usage)
    "chunk_text",
    "list_strategies",
    "detect_strategy",
    
    # Built-in strategies (voor direct gebruik of extension)
    "DefaultStrategy",
    "FreeTextStrategy",
    "FinancialTablesStrategy",
    "LegalDocumentsStrategy",
    "AdministrativeDocumentsStrategy",
    "ReviewsStrategy",
    "MenusStrategy",
]
