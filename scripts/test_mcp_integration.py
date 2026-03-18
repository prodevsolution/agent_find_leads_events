import logging
import sys
import os

# Añadir el directorio actual al path para importar tools
sys.path.append(os.getcwd())

from tools import scrape_dynamic_mcp
from graph import scraper_node, GraphState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_scraper_selection():
    print("\n--- Test 1: Verificación de Selección de Scraper ---")
    state = {
        "urls_to_scrape": [
            "https://www.linkedin.com/company/eventra-test",
            "https://www.google.com/events"
        ],
        "current_date": "2026-03-17"
    }
    
    # Simulamos el nodo de scraping
    print("Probando detección de dominios dinámicos...")
    for url in state["urls_to_scrape"]:
        dynamic_domains = ["linkedin.com", "instagram.com", "facebook.com", "tiktok.com", "twitter.com"]
        is_dynamic = any(domain in url.lower() for domain in dynamic_domains)
        print(f"URL: {url} | Es Dinámico: {is_dynamic}")

def test_dynamic_tool_structure():
    print("\n--- Test 2: Verificación de Estructura de Salida ---")
    url = "https://www.linkedin.com/company/prodevsolution"
    result = scrape_dynamic_mcp.invoke({"url": url})
    
    print(f"Resultado para {url}:")
    print(f"- Titulo: {result.get('title')}")
    print(f"- Content length: {len(result.get('content'))}")
    print(f"- Emails encontrados: {result.get('emails')}")

if __name__ == "__main__":
    test_scraper_selection()
    test_dynamic_tool_structure()
