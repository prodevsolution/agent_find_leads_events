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
niches = [
    "Circus", "Concerts", "Theater", "Community Events", "Festivals", 
    "Street Fairs", "Cultural Events", "Outdoor Events", "Carnivals", "Agricultural Shows"
]

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
    queries = [f"{niche} events" for niche in niches]

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


if __name__ == "__main__":
    logger.info("Starting Event Prospecting System...")
    
    # Initialize DB (just creating tables if not exists)
    _ = repository.get_stats() 
    
    # Start background scheduler
    start_scheduler()
    
    # Launch Gradio server
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
