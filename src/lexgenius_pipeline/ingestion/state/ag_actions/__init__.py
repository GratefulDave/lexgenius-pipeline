"""State Attorney General action connectors.

Connectors for ingesting press releases, enforcement actions, and legal
announcements from state Attorney General offices. Each connector filters
for mass-tort-relevant content (consumer protection, pharma, environmental,
data privacy, product liability, etc.).
"""

from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector

# ── Individual state connectors ──────────────────────────────────────
from lexgenius_pipeline.ingestion.state.ag_actions.ca import CaliforniaAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.co import ColoradoAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.fl import FloridaAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.il import IllinoisAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.ma import MassachusettsAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.nc import NorthCarolinaAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.ny import NewYorkAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.oh import OhioAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.pa import PennsylvaniaAGConnector
from lexgenius_pipeline.ingestion.state.ag_actions.tx import TexasAGConnector

__all__ = [
    "BaseAGActionsConnector",
    "CaliforniaAGConnector",
    "ColoradoAGConnector",
    "FloridaAGConnector",
    "IllinoisAGConnector",
    "MassachusettsAGConnector",
    "NorthCarolinaAGConnector",
    "NewYorkAGConnector",
    "OhioAGConnector",
    "PennsylvaniaAGConnector",
    "TexasAGConnector",
]

ALL_AG_CONNECTORS: list[type[BaseAGActionsConnector]] = [
    CaliforniaAGConnector,
    ColoradoAGConnector,
    FloridaAGConnector,
    IllinoisAGConnector,
    MassachusettsAGConnector,
    NorthCarolinaAGConnector,
    NewYorkAGConnector,
    OhioAGConnector,
    PennsylvaniaAGConnector,
    TexasAGConnector,
]
