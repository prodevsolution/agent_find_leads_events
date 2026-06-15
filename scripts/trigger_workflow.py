import sys
import os
from datetime import datetime
import logging

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import graph
from database import repository

# Configure logging for console
logging.basicConfig(level=logging.INFO)

def trigger():
    print("--- Manually Triggering Workflow ---")
    
    niches = ["Circus productions"]
    current_date = datetime.now().strftime("%Y-%m-%d")
    start_date = "2026-03-20"
    end_date = "9999-12-31"
    
    initial_state = {
        "search_queries": niches,
        "search_criteria": "",
        "brainstormed_entities": [],
        "summarizer_leads": [],
        "scraper_leads": [],
        "start_date": start_date,
        "end_date": end_date,
        "current_date": current_date,
        "urls_to_scrape": [],
        "scraped_leads": [],
        "saved_leads": [],
        "marketed_leads": [],
        "notifications_sent": False,
        "max_results": 10
    }

    print(f"Invoking graph for niche: {niches}")
    try:
        # Avoid using the global app_graph which might have state from previous failed imports
        workflow = graph.build_graph()
        result = workflow.invoke(initial_state)
        print(f"Workflow finished. Saved leads count: {len(result.get('saved_leads', []))}")
    except Exception as e:
        print(f"Workflow failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    trigger()
