import os
import time
import logging
from datetime import datetime, timedelta
import threading

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from database import repository
from graph import app_graph
from config import EXTRA_NICHES

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
    """Combines default niches with those from environment variables."""
    n_list = [n.strip() for n in DEFAULT_NICHES]
    if EXTRA_NICHES:
        extra = [n.strip() for n in EXTRA_NICHES.split(",") if n.strip()]
        for e in extra:
            if e.lower() not in [x.lower() for x in n_list]:
                n_list.append(e)
    return sorted(n_list, key=str.lower)

# Active niches state (managed at runtime)
active_niches = get_initial_niches()

def add_niche(niche_name: str):
    """Adds a new niche to the active list if it doesn't already exist (lexicographically)."""
    global active_niches
    niche_name = niche_name.strip()
    if not niche_name:
        return active_niches
    
    current_lower = [n.lower() for n in active_niches]
    if niche_name.lower() not in current_lower:
        active_niches.append(niche_name)
        active_niches = sorted(active_niches, key=str.lower)
    return active_niches

def remove_niche(niche_name: str):
    """Removes a niche from the active list."""
    global active_niches
    if niche_name in active_niches:
        active_niches.remove(niche_name)
    return active_niches

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
    queries = [f"{n_name} events" for n_name in active_niches]

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

def ui_add_niche(new_niche):
    if not new_niche:
        return gr.update(choices=active_niches), "Please enter a niche name."
    updated = add_niche(new_niche)
    return gr.update(choices=updated, value=new_niche), f"Niche '{new_niche}' added successfully."

def ui_remove_niche(selected_niche):
    if not selected_niche:
        return gr.update(choices=active_niches), "Please select a niche to remove."
    updated = remove_niche(selected_niche)
    return gr.update(choices=updated, value=None), f"Niche '{selected_niche}' removed successfully."


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
            trigger_output = gr.Textbox(label="Status Message", interactive=False)
            
        with gr.Column():
            gr.Markdown("### 👥 Recent Leads (Top 10)")
            leads_table = gr.Dataframe(
                headers=["Name", "Email", "Event", "Status"],
                datatype=["str", "str", "str", "str"],
                col_count=(4, "fixed"),
                interactive=False
            )
            refresh_btn = gr.Button("Refresh Dashboard")

        with gr.Column():
            gr.Markdown("### 📂 Manage Niches")
            niche_list_ui = gr.Dropdown(
                choices=active_niches, 
                label="Current Niches (Select one to remove)", 
                interactive=True
            )
            remove_niche_btn = gr.Button("Remove Selected Niche", variant="secondary")
            new_niche_input = gr.Textbox(label="Add New Niche", placeholder="e.g. Tech Conferences")
            add_niche_btn = gr.Button("Add Niche")
            add_niche_status = gr.Markdown("")
            
            gr.Markdown("> [!NOTE]\n> Changes to niches are applied to the next run.")

    # Wire up events
    refresh_btn.click(
        fn=refresh_dashboard,
        outputs=[status_panel, stats_panel, leads_table]
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
    
    add_niche_btn.click(
        fn=ui_add_niche,
        inputs=[new_niche_input],
        outputs=[niche_list_ui, add_niche_status]
    )
    
    remove_niche_btn.click(
        fn=ui_remove_niche,
        inputs=[niche_list_ui],
        outputs=[niche_list_ui, add_niche_status]
    )


if __name__ == "__main__":
    logger.info("Starting Event Prospecting System...")
    
    # Initialize DB (just creating tables if not exists)
    _ = repository.get_stats() 
    
    # Start background scheduler
    start_scheduler()
    
    # Launch Gradio server
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
