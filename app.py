import os
import time
import logging
from datetime import datetime, timedelta
import threading

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from database import repository
from graph import app_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state for UI
AGENT_STATUS = "Idle"
LAST_RUN = "Never"
NEXT_RUN = "Pending..."

# Default search configurations
DEFAULT_NICHES = [
    "Circus productions", "Touring theater", "Magic shows", "Ice shows", 
    "Touring musical productions", "County fairs", "State fairs", "Agricultural shows"
]

def get_initial_niches():
    niches = set([n.lower() for n in DEFAULT_NICHES])
    extra_str = os.getenv("EXTRA_NICHES", "")
    if extra_str:
        for ext in extra_str.split(','):
            ext = ext.strip().lower()
            if ext:
                niches.add(ext)
    
    # Capitalize for display and sort
    return sorted([n.capitalize() for n in niches])

active_niches = get_initial_niches()

def add_niche(new_niche: str):
    new_niche = new_niche.strip()
    if not new_niche:
        return "Niche cannot be empty", gr.Dropdown(choices=active_niches)
    
    new_lower = new_niche.lower()
    for existing in active_niches:
        if existing.lower() == new_lower:
            return f"Niche '{new_niche}' already exists.", gr.Dropdown(choices=active_niches)
            
    active_niches.append(new_niche)
    active_niches.sort()
    logger.info(f"Added new niche: {new_niche}")
    return f"Added '{new_niche}' successfully.", gr.Dropdown(choices=active_niches)

def remove_niche(selected_niche: str):
    if not selected_niche:
        return "Please select a niche to remove.", gr.Dropdown(choices=active_niches)
        
    for i, existing in enumerate(active_niches):
        if existing == selected_niche:
            removed = active_niches.pop(i)
            logger.info(f"Removed niche: {removed}")
            return f"Removed '{removed}' successfully.", gr.Dropdown(choices=active_niches, value=None)
            
    return f"Niche '{selected_niche}' not found.", gr.Dropdown(choices=active_niches)

def format_date(dt: datetime) -> str:
    """Format datetime to ISO 8601 string part (YYYY-MM-DD)."""
    return dt.strftime("%Y-%m-%d")

def get_default_dates():
    start_date = datetime.now() + timedelta(days=2)
    return format_date(start_date), "9999-12-31"

def run_agent_workflow(override_start=None, override_end=None):
    """
    Executes the LangGraph multi-agent workflow.
    Can be parameterized with override dates from the UI.
    """
    global AGENT_STATUS, LAST_RUN
    if AGENT_STATUS == "Running":
        logger.warning("Workflow is already running. Skipping this execution.")
        return
        
    AGENT_STATUS = "Running"
    logger.info("Starting Multi-Agent Workflow")
    
    current_date = format_date(datetime.now())
    start_date, end_date = get_default_dates()
    
    # Apply manual overrides if provided and valid
    if override_start:
        start_date = override_start
    if override_end:
        end_date = override_end
        
    # Construct base queries
    queries = [f"{niche} events" for niche in active_niches]

    initial_state = {
        "search_queries": queries,
        "start_date": start_date,
        "end_date": end_date,
        "current_date": current_date,
        "urls_to_scrape": [],
        "scraped_leads": [],
        "saved_leads": [],
        "marketed_leads": [],
        "notifications_sent": False
    }

    try:
        # Invoke LangGraph
        result = app_graph.invoke(initial_state)
        logger.info(f"Workflow completed successfully. Pushed {len(result.get('marketed_leads', []))} leads.")
    except Exception as e:
        logger.error(f"Error during workflow execution: {e}")
    finally:
        AGENT_STATUS = "Idle"
        LAST_RUN = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- Scheduler Setup ---
scheduler = BackgroundScheduler()

def start_scheduler():
    # Run every 6 hours
    scheduler.add_job(run_agent_workflow, 'interval', hours=6, id='event_prospecting_job', replace_existing=True)
    scheduler.start()
    logger.info("APScheduler started. Job will run every 6 hours.")
    
    # Update NEXT_RUN for UI
    global NEXT_RUN
    job = scheduler.get_job('event_prospecting_job')
    if job and job.next_run_time:
        NEXT_RUN = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")


# --- Gradio UI ---
def refresh_dashboard():
    stats = repository.get_stats()
    leads = repository.get_recent_leads(10)
    
    # Formatting for Grid
    recent_leads_data = [
        [lead.name or "N/A", lead.email, lead.event_name or "N/A", lead.status] 
        for lead in leads
    ]
    
    # Updating NEXT_RUN logic dynamically
    global NEXT_RUN
    if scheduler.running:
        job = scheduler.get_job('event_prospecting_job')
        if job and job.next_run_time:
            NEXT_RUN = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            
    status_markdown = f"""
    ### 🔄 System Status
    - **Current State**: {AGENT_STATUS}
    - **Last Run**: {LAST_RUN}
    - **Next Scheduled Run**: {NEXT_RUN}
    """
    
    stats_markdown = f"""
    ### 📊 Lead Statistics
    - **Total Leads Collected**: {stats['total_leads']}
    - **Emails Sent (Mailchimp)**: {stats['sent_count']}
    - **Responses Detected**: {stats['responded_count']}
    """
    
    return status_markdown, stats_markdown, recent_leads_data

def manual_trigger(start_date_ui, end_date_ui):
    if AGENT_STATUS == "Running":
        return "Agents are already running. Please wait...", refresh_dashboard()
    
    # Run in a separate thread so Gradio doesn't block
    thread = threading.Thread(target=run_agent_workflow, args=(start_date_ui, end_date_ui))
    thread.start()
    
    return "Workflow triggered manually. Refresh dashboard to see updates.", refresh_dashboard()

def clear_db_action():
    if AGENT_STATUS == "Running":
        return "Cannot clear database while agents are running.", refresh_dashboard()
    success = repository.clear_database()
    if success:
        return "Database cleared successfully.", refresh_dashboard()
    return "Failed to clear database. Check logs.", refresh_dashboard()

def stop_server_action():
    logger.info("Stopping Server gracefully via UI...")
    os._exit(0)



with gr.Blocks(title="Event Prospecting Multi-Agent Monitor") as demo:
    gr.Markdown("# 🚀 Event Prospecting Multi-Agent System")
    gr.Markdown("Monitoring dashboard for LangGraph agents finding events across niches.")
    
    with gr.Row():
        status_panel = gr.Markdown("Loading status...")
        stats_panel = gr.Markdown("Loading stats...")
        
    with gr.Row():
        with gr.Column():
            gr.Markdown("### ⚙️ Manual Actions")
            start_date_input = gr.Textbox(
                label="Start Date Override (YYYY-MM-DD)", 
                placeholder="Leave empty for default (Today + 2 days)"
            )
            end_date_input = gr.Textbox(
                label="End Date Override (YYYY-MM-DD)", 
                placeholder="Leave empty for default (Infinity)"
            )
            trigger_btn = gr.Button("Run Agents Now", variant="primary")
            
            with gr.Row():
                clear_db_btn = gr.Button("🗑️ Clear Database", variant="stop")
                stop_server_btn = gr.Button("🛑 Stop Server", variant="stop")
                
            trigger_output = gr.Textbox(label="Status Message", interactive=False)
            
            gr.Markdown("### 🎯 Niche Management")
            
            with gr.Row():
                niche_list_ui = gr.Dropdown(
                    label="Active Niches",
                    choices=active_niches,
                    interactive=True
                )
                remove_niche_btn = gr.Button("Remove Selected")
                
            with gr.Row():
                new_niche_input = gr.Textbox(label="New Niche", placeholder="e.g. Anime Conventions")
                add_niche_btn = gr.Button("Add Niche")
                
            add_niche_status = gr.Textbox(label="Niche Update Status", interactive=False)
            
            add_niche_btn.click(
                fn=add_niche,
                inputs=[new_niche_input],
                outputs=[add_niche_status, niche_list_ui]
            )
            remove_niche_btn.click(
                fn=remove_niche,
                inputs=[niche_list_ui],
                outputs=[add_niche_status, niche_list_ui]
            )
            
            # End of Column 1

            
        with gr.Column():
            gr.Markdown("### 👥 Recent Leads (Top 10)")
            leads_table = gr.Dataframe(
                headers=["Name", "Email", "Event", "Status"],
                datatype=["str", "str", "str", "str"],
                col_count=(4, "fixed"),
                interactive=False
            )
            refresh_btn = gr.Button("Refresh Dashboard")

    # Wire up events
    refresh_btn.click(
        fn=refresh_dashboard,
        outputs=[status_panel, stats_panel, leads_table]
    )
    
    # Wrapper for clear DB
    def clear_db_wrapper():
        msg, (s1, s2, table) = clear_db_action()
        return msg, s1, s2, table
        
    clear_db_btn.click(
        fn=clear_db_wrapper,
        inputs=None,
        outputs=[trigger_output, status_panel, stats_panel, leads_table]
    )
    
    stop_server_btn.click(
        fn=stop_server_action,
        inputs=None,
        outputs=None
    )
    
    trigger_btn.click(
        fn=manual_trigger,
        inputs=[start_date_input, end_date_input],
        # The Gradio tuple output cannot map partially, so we wrap it
        outputs=None # Custom JS or just ignoring standard return for now, using a wrapper
    )
    
    # Wrapper for trigger
    def trigger_wrapper(start_date, end_date):
        msg, (s1, s2, table) = manual_trigger(start_date, end_date)
        return msg, s1, s2, table
        
    trigger_btn.click(
        fn=trigger_wrapper,
        inputs=[start_date_input, end_date_input],
        outputs=[trigger_output, status_panel, stats_panel, leads_table]
    )

    demo.load(refresh_dashboard, None, [status_panel, stats_panel, leads_table])


if __name__ == "__main__":
    logger.info("Starting Event Prospecting System...")
    
    # Initialize DB (just creating tables if not exists)
    _ = repository.get_stats() 
    
    # Start background scheduler
    start_scheduler()
    
    # Launch Gradio server
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
