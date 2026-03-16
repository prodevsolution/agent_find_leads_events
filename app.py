import os
import time
import logging
from datetime import datetime, timedelta
import threading
import json

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from database import repository
from graph import app_graph
import config

# Configure logging to both console and file
log_file = "agent.log"
file_handler = logging.FileHandler(log_file, encoding='utf-8')
stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, stream_handler]
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

NICHES_FILE = "active_niches.json"

def get_initial_niches():
    if os.path.exists(NICHES_FILE):
        try:
            with open(NICHES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {NICHES_FILE}: {e}")

    niches = set([n.lower() for n in DEFAULT_NICHES])
    extra_str = os.getenv("EXTRA_NICHES", "")
    if extra_str:
        for ext in extra_str.split(','):
            ext = ext.strip().lower()
            if ext:
                niches.add(ext)
    
    # Capitalize for display and sort
    initial_niches = sorted([n.capitalize() for n in niches])
    save_niches(initial_niches)
    return initial_niches

def save_niches(niches):
    try:
        with open(NICHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(niches, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {NICHES_FILE}: {e}")

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
    save_niches(active_niches)
    logger.info(f"Added new niche: {new_niche}")
    return f"Added '{new_niche}' successfully.", gr.Dropdown(choices=active_niches)

def remove_niche(selected_niche: str):
    if not selected_niche:
        return "Please select a niche to remove.", gr.Dropdown(choices=active_niches)
        
    for i, existing in enumerate(active_niches):
        if existing == selected_niche:
            removed = active_niches.pop(i)
            save_niches(active_niches)
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
    else:
        end_date = "9999-12-31" # Default if not provided
        
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
def get_recent_logs(level_filter="ALL"):
    """Reads the last 50 lines from agent.log and filters by level."""
    if not os.path.exists(log_file):
        return "No logs yet."
    
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
            
        recent_lines = lines[-50:]
        if level_filter == "ALL":
            filtered = recent_lines
        else:
            filtered = [l for l in recent_lines if f"- {level_filter} -" in l]
            
        return "".join(filtered)
    except Exception as e:
        return f"Error reading logs: {e}"

def refresh_dashboard(log_level="ALL", page=1):
    stats = repository.get_stats()
    all_leads = repository.get_recent_leads(None)
    logs = get_recent_logs(log_level)
    
    items_per_page = 10
    total_pages = max(1, (len(all_leads) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    leads_to_show = all_leads[start_idx:end_idx]
    
    # Formatting for Grid
    recent_leads_data = [
        [lead.name or "N/A", lead.email, lead.event_name or "N/A", lead.event_url or "N/A", lead.status] 
        for lead in leads_to_show
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
    
    btn_label = "Running Agents..." if AGENT_STATUS == "Running" else "Run Agents Now"
    btn_interactive = (AGENT_STATUS != "Running")

    return status_markdown, stats_markdown, recent_leads_data, logs, f"Page {page} of {total_pages}", page, gr.update(value=btn_label, interactive=btn_interactive)

def manual_trigger(start_date_ui, end_date_ui):
    if AGENT_STATUS == "Running":
        return "Agents are already running. Please wait..."
    
    # Validation logic
    now_str = format_date(datetime.now())
    try:
        def to_str(val):
            if not val: return None
            if isinstance(val, (int, float)):
                # Handle milliseconds vs seconds
                if val > 1e11: 
                    val /= 1000.0
                dt_obj = datetime.fromtimestamp(val)
                return format_date(dt_obj)
            if isinstance(val, str):
                return val
            return format_date(val) # assuming it's a datetime object

        s_date = to_str(start_date_ui)
        e_date = to_str(end_date_ui) or "9999-12-31"

        logger.info(f"UI Trigger Validation: Start={s_date}, End={e_date}, Now={now_str}")

        if not s_date:
            return "[ERROR] Start date is required."

        if s_date < now_str:
            return f"[ERROR] Start date ({s_date}) cannot be in the past (today is {now_str})."
        if e_date <= s_date:
            return f"[ERROR] End date ({e_date}) must be strictly after Start date ({s_date})."
        
        start_date_to_run = s_date
        end_date_to_run = e_date
    except Exception as e:
        logger.error(f"Date validation error: {e}", exc_info=True)
        return f"[ERROR] Date validation failed: {e}"

    # Run in a separate thread so Gradio doesn't block
    thread = threading.Thread(target=run_agent_workflow, args=(start_date_to_run, end_date_to_run))
    thread.start()
    
    return "[SUCCESS] Workflow triggered! The UI will auto-refresh while agents are running."

def clear_db_action(log_level="ALL", page=1):
    if AGENT_STATUS == "Running":
        return "Cannot clear database while agents are running.", refresh_dashboard(log_level, page)
    success = repository.clear_database()
    if success:
        return "Database cleared successfully.", refresh_dashboard(log_level, 1)
    return "Failed to clear database. Check logs.", refresh_dashboard(log_level, page)

def clear_logs_action(log_level="ALL", page=1):
    """Truncates the log file and refreshes UI."""
    try:
        with open(log_file, "w", encoding='utf-8') as f:
            f.write("")
        return "Logs cleared.", refresh_dashboard(log_level, page)
    except Exception as e:
        return f"Error clearing logs: {e}", refresh_dashboard(log_level, page)

def stop_server_action():
    logger.info("Stopping Server gracefully via UI...")
    os._exit(0)



with gr.Blocks(title="Event Prospecting Multi-Agent Monitor") as demo:
    gr.Markdown("# 🚀 Event Prospecting Multi-Agent System")
    gr.Markdown("Monitoring dashboard for LangGraph agents finding events across niches.")
    
    with gr.Row():
        status_panel = gr.Markdown("Loading status...")
        stats_panel = gr.Markdown("Loading stats...")
        current_page = gr.State(1)
        
    with gr.Row():
        with gr.Column():
            gr.Markdown("### ⚙️ Manual Actions")
            d_start, d_end = get_default_dates()
            start_date_input = gr.DateTime(
                label="Start Date", 
                value=d_start,
                include_time=False
            )
            end_date_input = gr.DateTime(
                label="End Date (Optional)", 
                value=None, 
                include_time=False
            )
            gr.Markdown("> [!NOTE]\n> End date is optional. If left empty, search will encompass all future events.")
            trigger_btn = gr.Button("Run Agents Now", variant="primary")
            
            with gr.Row():
                clear_db_btn = gr.Button("🗑️ Clear Database", variant="stop")
                stop_server_btn = gr.Button("🛑 Stop Server", variant="stop")
                
            trigger_output = gr.Textbox(label="Status Message", interactive=False)
            
            add_niche_status = gr.Textbox(label="Niche Update Status", interactive=False)

            gr.Markdown("### 🚫 Excluded Domains")
            excluded_list = ", ".join(config.EXCLUDE_DOMAINS)
            gr.Markdown(f"Searching will ignore leads from: `{excluded_list}`")
            
            with gr.Accordion("Manage Niches", open=True):
                with gr.Row():
                    niche_list_ui = gr.Dropdown(
                        label="Active Niches (Used for search)",
                        choices=active_niches,
                        interactive=True
                    )
                    remove_niche_btn = gr.Button("Remove Selected")
                
                with gr.Row():
                    default_niche_ui = gr.Dropdown(
                        label="Default Niches",
                        choices=DEFAULT_NICHES,
                        interactive=True
                    )
                    add_default_btn = gr.Button("Add from Default")

                with gr.Row():
                    new_niche_input = gr.Textbox(label="New Custom Niche", placeholder="e.g. Anime Conventions")
                    add_niche_btn = gr.Button("Add Custom Niche")
                
            def add_default_niche(niche):
                if not niche:
                    return "Select a niche first", gr.Dropdown(choices=active_niches)
                return add_niche(niche)

            add_default_btn.click(
                fn=add_default_niche,
                inputs=[default_niche_ui],
                outputs=[add_niche_status, niche_list_ui]
            )
            
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
            gr.Markdown("### 👥 All Leads (Paginated)")
            leads_table = gr.Dataframe(
                headers=["Name", "Email", "Event", "Address", "Status"],
                datatype=["str", "str", "str", "str", "str"],
                column_count=(5, "fixed"),
                interactive=False
            )
            with gr.Row():
                prev_page_btn = gr.Button("◀ Previous")
                page_info = gr.Markdown("Page 1 of 1")
                next_page_btn = gr.Button("Next ▶")
            refresh_btn = gr.Button("Refresh Dashboard")

        with gr.Column():
            gr.Markdown("### 📜 Activity Logs")
            log_filter = gr.Dropdown(
                label="Log Level Filter",
                choices=["ALL", "INFO", "WARNING", "ERROR"],
                value="ALL"
            )
            clear_logs_btn = gr.Button("🗑️ Clear Log File", variant="secondary")
            log_display = gr.Code(
                label="Recent Activity",
                language="python",
                lines=20,
                interactive=False
            )

    # Auto-refresh timer: fires every 5 seconds, active only while agents are running
    live_timer = gr.Timer(value=5, active=False)
    
    def auto_refresh(level, page):
        """Called by timer - returns dashboard data + updates timer active state."""
        s, st, tbl, logs, p_info, p_num, btn_upd = refresh_dashboard(level, page)
        # Keep timer active while workflow is running, deactivate when idle
        is_running = (AGENT_STATUS == "Running")
        return s, st, tbl, logs, p_info, p_num, btn_upd, gr.Timer(active=is_running)

    live_timer.tick(
        fn=auto_refresh,
        inputs=[log_filter, current_page],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn, live_timer]
    )

    # Wire up events
    refresh_btn.click(
        fn=refresh_dashboard,
        inputs=[log_filter, current_page],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    def go_prev_page(level, page):
        return refresh_dashboard(level, page - 1)
        
    def go_next_page(level, page):
        return refresh_dashboard(level, page + 1)
        
    prev_page_btn.click(
        fn=go_prev_page,
        inputs=[log_filter, current_page],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    next_page_btn.click(
        fn=go_next_page,
        inputs=[log_filter, current_page],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    # Wrapper for clear DB
    def clear_db_wrapper(level, page):
        msg, (s1, s2, table, logs, p_info, p_num, b_upd) = clear_db_action(level, page)
        return msg, s1, s2, table, logs, p_info, p_num, b_upd
        
    clear_db_btn.click(
        fn=clear_db_wrapper,
        inputs=[log_filter, current_page],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )

    def clear_logs_wrapper(level, page):
        msg, (s1, s2, table, logs, p_info, p_num, b_upd) = clear_logs_action(level, page)
        return msg, s1, s2, table, logs, p_info, p_num, b_upd

    clear_logs_btn.click(
        fn=clear_logs_wrapper,
        inputs=[log_filter, current_page],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    stop_server_btn.click(
        fn=stop_server_action,
        inputs=None,
        outputs=None
    )
    
    # Wrapper for trigger: starts the workflow, activates the live timer
    def trigger_wrapper(start_date, end_date, level, page):
        msg = manual_trigger(start_date, end_date)
        s, st, tbl, logs, p_info, p_num, btn_upd = refresh_dashboard(level, page)
        return msg, s, st, tbl, logs, p_info, p_num, btn_upd, gr.Timer(active=True)
        
    trigger_btn.click(
        fn=trigger_wrapper,
        inputs=[start_date_input, end_date_input, log_filter, current_page],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn, live_timer]
    )

    def load_niches_for_ui():
        return gr.Dropdown(choices=active_niches)

    demo.load(refresh_dashboard, inputs=[log_filter, current_page], outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn])
    demo.load(load_niches_for_ui, inputs=[], outputs=[niche_list_ui])

if __name__ == "__main__":
    logger.info("Starting Event Prospecting System...")
    
    # Initialize DB (just creating tables if not exists)
    _ = repository.get_stats() 
    
    # Start background scheduler
    start_scheduler()
    
    # Launch Gradio server
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
