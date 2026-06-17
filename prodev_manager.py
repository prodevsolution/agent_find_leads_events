"""
prodev_manager.py
-----------------
Central module for ProDev Solution prospecting personas.
Loads persona definitions from prodev_personas.json and provides
helpers used by the Gradio UI (app.py) and the LangGraph workflow.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to the configurable personas file
PERSONAS_FILE = Path(__file__).parent / "prodev_personas.json"

# ── Persona loading ────────────────────────────────────────────────────────────

def load_personas() -> dict:
    """Load persona definitions from prodev_personas.json."""
    if not PERSONAS_FILE.exists():
        logger.warning(f"prodev_personas.json not found at {PERSONAS_FILE}")
        return {}
    try:
        with open(PERSONAS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Filter out comment keys
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        logger.error(f"Error loading personas: {e}")
        return {}


def save_personas(personas: dict) -> bool:
    """Persist updated persona definitions back to JSON."""
    try:
        # Preserve the comment key
        full = {"_comment": "Edita las listas de 'queries' libremente."}
        full.update(personas)
        with open(PERSONAS_FILE, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        logger.info("prodev_personas.json saved successfully.")
        return True
    except Exception as e:
        logger.error(f"Error saving personas: {e}")
        return False


def get_persona_names() -> dict:
    """Returns {key: display_name} for all personas + old_client option."""
    personas = load_personas()
    names = {k: v.get("name", k) for k, v in personas.items()}
    names["old_client"] = "Persona 5 — Clientes Antiguos (Importar / Manual)"
    return names


def get_persona_queries(persona_key: str) -> list[str]:
    """Returns the query list for a given persona key."""
    personas = load_personas()
    if persona_key == "old_client":
        return []
    return personas.get(persona_key, {}).get("queries", [])


def get_persona_criteria(persona_key: str) -> str:
    """Returns the criteria string for a given persona key."""
    personas = load_personas()
    return personas.get(persona_key, {}).get("criteria", "")


def get_persona_product(persona_key: str) -> str:
    """Returns the target product for a given persona key."""
    personas = load_personas()
    return personas.get(persona_key, {}).get("product", "")


def update_persona_queries(persona_key: str, new_queries: list[str]) -> bool:
    """
    Updates the queries for a persona and persists to JSON.
    Used by the UI query editor.
    """
    personas = load_personas()
    if persona_key not in personas:
        logger.error(f"Persona key '{persona_key}' not found.")
        return False
    personas[persona_key]["queries"] = new_queries
    return save_personas(personas)


# ── CSV Template ───────────────────────────────────────────────────────────────

CSV_TEMPLATE_HEADER = (
    "Nombre,Empresa,Email,Telefono,Sitio Web,Ciudad,Pais,"
    "Ultimo Contacto,Producto Usado,Notas\n"
)
CSV_TEMPLATE_EXAMPLE = (
    "Juan Perez,Empresa XYZ,juan@empresa.com,+1-305-555-1234,"
    "www.empresa.com,Miami,USA,2024-01-15,Custom Dev,"
    "Cliente satisfecho. Proyecto completado.\n"
    "Maria Lopez,Transport Caribe LLC,,+1-787-555-9876,,"
    "San Juan,Puerto Rico,2023-06-20,TravelorHub,"
    "Pidio cotizacion pero no cerro por presupuesto.\n"
)

def get_csv_template() -> str:
    """Returns a CSV template string ready for download."""
    return CSV_TEMPLATE_HEADER + CSV_TEMPLATE_EXAMPLE


# ── UI Helpers ─────────────────────────────────────────────────────────────────

def queries_list_to_text(queries: list[str]) -> str:
    """Converts a list of query strings to a newline-separated text block for UI display."""
    return "\n".join(queries)


def queries_text_to_list(text: str) -> list[str]:
    """Converts a newline-separated text block back to a cleaned list of queries."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_gradio_persona_choices() -> list[tuple[str, str]]:
    """
    Returns a list of (display_name, key) tuples for a Gradio Dropdown.
    """
    return [(name, key) for key, name in get_persona_names().items()]
