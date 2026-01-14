"""
Chunking Strategies

Verzameling van alle beschikbare chunking strategieën.
Elke strategie is geoptimaliseerd voor een specifiek type data.
"""
from .default import DefaultStrategy
from .free_text import FreeTextStrategy
from .financial_tables import FinancialTablesStrategy
from .legal import LegalDocumentsStrategy
from .administrative import AdministrativeDocumentsStrategy
from .reviews import ReviewsStrategy
from .menus import MenusStrategy

__all__ = [
    "DefaultStrategy",
    "FreeTextStrategy",
    "FinancialTablesStrategy",
    "LegalDocumentsStrategy",
    "AdministrativeDocumentsStrategy",
    "ReviewsStrategy",
    "MenusStrategy",
]
