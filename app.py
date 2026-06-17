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

# Global state for UI (using generic locks or just being careful with assignments)
status_lock = threading.Lock()
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

def run_agent_workflow(override_start=None, override_end=None, override_criteria=None, max_results=15, persona_key=None, sync_mailchimp=None):
    """
    Executes the LangGraph multi-agent workflow.
    Can be parameterized with override dates from the UI or a ProDev persona.
    """
    global AGENT_STATUS, LAST_RUN
    with status_lock:
        if AGENT_STATUS == "Running":
            logger.warning("Workflow is already running. Skipping this execution.")
            return
        AGENT_STATUS = "Running"
        
    logger.info(f"Starting Multi-Agent Workflow (Persona={persona_key}, SyncMailchimp={sync_mailchimp})")
    
    try:
        from prodev_manager import get_persona_queries, get_persona_product, get_persona_criteria
        current_date = format_date(datetime.now())
        start_date, end_date = get_default_dates()
        
        # Apply manual overrides if provided and valid
        if override_start:
            start_date = override_start
        if override_end:
            end_date = override_end
        else:
            end_date = "9999-12-31" 
            
        if persona_key and persona_key != "old_client":
            queries = get_persona_queries(persona_key)
            target_product = get_persona_product(persona_key)
            persona_criteria = get_persona_criteria(persona_key)
            combined_criteria = f"{persona_criteria} {override_criteria or ''}".strip()
        else:
            queries = [niche for niche in active_niches]
            target_product = None
            combined_criteria = override_criteria or ""

        initial_state = {
            "search_queries": queries,
            "search_criteria": combined_criteria,
            "brainstormed_entities": [],
            "summarizer_leads": [],
            "scraper_leads": [],
            "agentic_leads": [],          # NEW: agentic researcher path
            "all_search_content": [],     # NEW: accumulated search content
            "start_date": start_date,
            "end_date": end_date,
            "current_date": current_date,
            "urls_to_scrape": [],
            "scraped_leads": [],
            "saved_leads": [],
            "marketed_leads": [],
            "notifications_sent": False,
            "max_results": max_results,
            "persona_type": persona_key,
            "target_product": target_product,
            "sync_mailchimp": sync_mailchimp
        }

        # Invoke LangGraph
        result = app_graph.invoke(initial_state)
        logger.info(f"Workflow completed successfully. Pushed {len(result.get('marketed_leads', []))} leads.")
    except Exception as e:
        logger.error(f"Error during workflow execution: {e}")
    finally:
        with status_lock:
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
        with open(log_file, "r", encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            
        recent_lines = lines[-50:]
        if level_filter == "ALL":
            filtered = recent_lines
        else:
            filtered = [l for l in recent_lines if f"- {level_filter} -" in l]
            
        return "".join(filtered)
    except Exception as e:
        return f"Error reading logs: {e}"

def refresh_dashboard(log_level="ALL", page=1, persona_filter="All", product_filter="All"):
    stats = repository.get_stats()
    all_leads = repository.get_recent_leads(None, persona_type=persona_filter, target_product=product_filter)
    logs = get_recent_logs(log_level)
    
    items_per_page = 10
    total_pages = max(1, (len(all_leads) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    leads_to_show = all_leads[start_idx:end_idx]
    
    # Formatting for Grid (added Persona and Product columns)
    recent_leads_data = [
        [
            lead.name or "N/A", 
            lead.email or "N/A", 
            lead.phone or "N/A", 
            lead.event_name or "N/A", 
            lead.event_url or "N/A", 
            lead.persona_type or "N/A",
            lead.target_product or "N/A",
            lead.status
        ] 
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
    
    persona_stats = repository.get_stats_by_persona()
    p_stats_str = ""
    for p_type, count in persona_stats.items():
        p_stats_str += f"\n    - *{p_type}*: {count} leads"
    if not p_stats_str:
        p_stats_str = "\n    - No classified leads yet."

    stats_markdown = f"""
    ### 📊 Lead Statistics
    - **Total Leads Collected**: {stats['total_leads']}
    - **Emails Sent (Mailchimp)**: {stats['sent_count']}
    - **Responses Detected**: {stats['responded_count']}
    - **Leads by Persona**:{p_stats_str}
    """
    
    btn_label = "Running Agents..." if AGENT_STATUS == "Running" else "Run Agents Now"
    btn_interactive = (AGENT_STATUS != "Running")

    return status_markdown, stats_markdown, recent_leads_data, logs, f"Page {page} of {total_pages}", page, gr.update(value=btn_label, interactive=btn_interactive)

def manual_trigger(start_date_ui, end_date_ui, search_criteria_ui, max_results_ui, sync_mailchimp=False):
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
        s_criteria = search_criteria_ui or ""

        logger.info(f"UI Trigger Validation: Start={s_date}, End={e_date}, Criteria='{s_criteria}', Now={now_str}")

        if not s_date:
            return "[ERROR] Start date is required."

        if s_date < now_str:
            return f"[ERROR] Start date ({s_date}) cannot be in the past (today is {now_str})."
        if e_date <= s_date:
            return f"[ERROR] End date ({e_date}) must be strictly after Start date ({s_date})."
        
        start_date_to_run = s_date
        end_date_to_run = e_date
        criteria_to_run = s_criteria
        m_results = int(max_results_ui) if max_results_ui and int(max_results_ui) >= 5 else 15
    except Exception as e:
        logger.error(f"Validation error: {e}", exc_info=True)
        return f"[ERROR] Validation failed: {e}"

    # Run in a separate thread so Gradio doesn't block
    thread = threading.Thread(target=run_agent_workflow, args=(start_date_to_run, end_date_to_run, criteria_to_run, m_results), kwargs={"sync_mailchimp": sync_mailchimp})
    thread.start()
    
    return "[SUCCESS] Workflow triggered! The UI will auto-refresh while agents are running."

def clear_db_action(log_level="ALL", page=1, persona_filter="All", product_filter="All"):
    global AGENT_STATUS
    with status_lock:
        if AGENT_STATUS == "Running":
            return "Cannot clear database while agents are running.", *refresh_dashboard(log_level, page, persona_filter, product_filter)
    
    success = repository.clear_database()
    if success:
        # Explicitly force a dashboard refresh with empty data
        return "Database cleared successfully.", *refresh_dashboard(log_level, 1, persona_filter, product_filter)
    return "Failed to clear database. Check logs.", *refresh_dashboard(log_level, page, persona_filter, product_filter)

def clear_logs_action(log_level="ALL", page=1, persona_filter="All", product_filter="All"):
    """Truncates the log file and refreshes UI."""
    try:
        with open(log_file, "w", encoding='utf-8') as f:
            f.write("")
        return "Logs cleared.", refresh_dashboard(log_level, page, persona_filter, product_filter)
    except Exception as e:
        return f"Error clearing logs: {e}", refresh_dashboard(log_level, page, persona_filter, product_filter)

def stop_server_action():
    logger.info("Stopping Server gracefully via UI...")
    os._exit(0)



# --- ProDev & Old Clients UI Callbacks ---
import prodev_manager

def on_persona_select(persona_key):
    if not persona_key or persona_key == "old_client":
        return "", "", "", gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
    
    product = prodev_manager.get_persona_product(persona_key)
    criteria = prodev_manager.get_persona_criteria(persona_key)
    queries_list = prodev_manager.get_persona_queries(persona_key)
    queries_text = prodev_manager.queries_list_to_text(queries_list)
    
    return product, criteria, queries_text, gr.update(visible=True), gr.update(visible=True), gr.update(visible=True)

def on_save_queries(persona_key, queries_text):
    if not persona_key or persona_key == "old_client":
        return "Cannot save queries for this selection."
    
    queries = prodev_manager.queries_text_to_list(queries_text)
    success = prodev_manager.update_persona_queries(persona_key, queries)
    if success:
        return f"Saved {len(queries)} queries successfully for persona '{persona_key}'!"
    return "Failed to save queries."

def prodev_trigger_wrapper(persona_key, override_criteria, max_results, level, page, persona_filter="All", product_filter="All", sync_mailchimp=False):
    if AGENT_STATUS == "Running":
        return "Agents are already running. Please wait...", *refresh_dashboard(level, page, persona_filter, product_filter), gr.Timer(active=True)
    
    if not persona_key or persona_key == "old_client":
        return "[ERROR] Please select an active search persona.", *refresh_dashboard(level, page, persona_filter, product_filter), gr.Timer(active=False)
        
    m_results = int(max_results) if max_results and int(max_results) >= 5 else 15
    
    # Run in a separate thread
    thread = threading.Thread(target=run_agent_workflow, kwargs={
        "override_criteria": override_criteria,
        "max_results": m_results,
        "persona_key": persona_key,
        "sync_mailchimp": sync_mailchimp
    })
    thread.start()
    
    msg = f"[SUCCESS] ProDev Prospecting for '{persona_key}' triggered!"
    s, st, tbl, logs, p_info, p_num, btn_upd = refresh_dashboard(level, page, persona_filter, product_filter)
    return msg, s, st, tbl, logs, p_info, p_num, btn_upd, gr.Timer(active=True)

def on_add_manual_contact(name, company, email, phone, website, city, country, product, notes):
    try:
        lead, is_new = repository.add_manual_contact(
            name=name,
            company=company,
            email=email,
            phone=phone,
            website=website,
            city=city,
            country=country,
            product=product,
            notes=notes
        )
        if is_new:
            return f"✅ Contact added successfully: {lead.name or lead.email or lead.phone}"
        return f"⏭️ Contact already exists: {lead.name or lead.email or lead.phone}"
    except Exception as e:
        return f"❌ Error adding contact: {e}"

def on_import_csv(csv_text, file_obj):
    content = ""
    if file_obj is not None:
        try:
            with open(file_obj.name, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"Error reading uploaded file: {e}"
    elif csv_text and csv_text.strip():
        content = csv_text.strip()
    else:
        return "Please paste CSV content or upload a CSV file."
        
    res = repository.import_old_clients_csv(content)
    summary = (
        f"CSV Import Summary:\n"
        f"-------------------\n"
        f"Inserted: {res['inserted']}\n"
        f"Skipped: {res['skipped']}\n"
        f"Errors/Failed: {res['errors']}\n\n"
        f"Details:\n" + "\n".join(res['details'][:30])
    )
    if len(res['details']) > 30:
        summary += f"\n...and {len(res['details']) - 30} more rows."
    return summary


custom_css = """
.selectable-table {
    user-select: text !important;
    -webkit-user-select: text !important;
    -moz-user-select: text !important;
    -ms-user-select: text !important;
}

.selectable-table * {
    user-select: text !important;
    -webkit-user-select: text !important;
    -moz-user-select: text !important;
    -ms-user-select: text !important;
}

.selectable-table td, .selectable-table th {
    cursor: text !important;
}
"""

with gr.Blocks(title="Event & ProDev Prospecting Monitor") as demo:
    gr.Markdown("# 🚀 ProDev Solution Prospecting Multi-Agent System")
    gr.Markdown("Monitoring and lead extraction dashboard with dynamic search, persona configurations, and contact manager.")
    
    with gr.Row():
        status_panel = gr.Markdown("Loading status...")
        stats_panel = gr.Markdown("Loading stats...")
        current_page = gr.State(1)
        
    with gr.Row():
        sync_mailchimp_checkbox = gr.Checkbox(
            label="Sincronizar nuevos contactos con Mailchimp (Opcional)",
            value=config.ENABLE_MAILCHIMP_SYNC,
            info="Si está marcado, los nuevos prospectos con email se sincronizarán con la audiencia de Mailchimp en tiempo real."
        )
        
    with gr.Row():
        with gr.Column(scale=1):
            with gr.Tabs():
                # --- TAB 1: Event & Niche Prospecting ---
                with gr.TabItem("🌍 Event & Niche Prospecting"):
                    gr.Markdown("### ⚙️ Event Search Settings")
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
                    search_criteria_input = gr.Textbox(
                        label="Search Criteria", 
                        placeholder="e.g. + venues in Florida",
                        value=""
                    )
                    gr.Markdown("> [!TIP]\n> Use criteria like `+ venues in Florida` or `with contact emails` to narrow down results.")
                    
                    max_results_input = gr.Number(
                        label="Max Search Results", 
                        value=15, 
                        minimum=5, 
                        maximum=100,
                        step=1,
                        info="Suggested: 15. Minimum: 5."
                    )

                    trigger_btn = gr.Button("Run Agents Now", variant="primary")
                    trigger_output = gr.Textbox(label="Status Message", interactive=False)
                    
                    gr.Markdown("### 🚫 Excluded Domains")
                    excluded_list = ", ".join(config.EXCLUDE_DOMAINS)
                    gr.Markdown(f"Searching will ignore leads from: `{excluded_list}`")
                    
                    with gr.Accordion("Manage Niches", open=True):
                        add_niche_status = gr.Textbox(label="Niche Update Status", interactive=False)
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

                # --- TAB 2: ProDev Personas Prospecting ---
                with gr.TabItem("🎯 ProDev Personas"):
                    gr.Markdown("### 🔍 targeted Buyer Persona Searches")
                    persona_choices = prodev_manager.build_gradio_persona_choices()
                    
                    persona_selector = gr.Dropdown(
                        label="Select ProDev Buyer Persona",
                        choices=persona_choices,
                        value=persona_choices[0][1] if persona_choices else None
                    )
                    
                    persona_product_ui = gr.Textbox(label="Target Product", interactive=False)
                    persona_criteria_ui = gr.Textbox(label="Default Criteria", interactive=False)
                    
                    with gr.Accordion("Configure Search Queries List", open=True) as queries_accordion:
                        gr.Markdown("Modify the query list used by the agent when running searches for this persona:")
                        persona_queries_display = gr.TextArea(
                            label="Queries (one per line)", 
                            lines=8
                        )
                        save_queries_btn = gr.Button("💾 Save Queries List", size="sm")
                        queries_save_status = gr.Textbox(label="Save Status", interactive=False)
                    
                    gr.Markdown("### ⚡ Trigger Persona Prospecting Run")
                    prodev_extra_criteria = gr.Textbox(
                        label="Extra Search Criteria (Optional)",
                        placeholder="e.g. contact email Florida",
                        value=""
                    )
                    prodev_max_res = gr.Number(
                        label="Max Search Results per query", 
                        value=15, 
                        minimum=5, 
                        maximum=100,
                        step=1
                    )
                    prodev_run_btn = gr.Button("Run ProDev Agents Now", variant="primary")
                    prodev_status_output = gr.Textbox(label="Run Status Message", interactive=False)

                # --- TAB 3: Old Clients Manager ---
                with gr.TabItem("👥 Clientes Antiguos (Persona 5)"):
                    gr.Markdown("### 📝 Gestionar Contactos y Reactivación")
                    
                    with gr.Tabs():
                        with gr.TabItem("Manual"):
                            gr.Markdown("#### Registrar Contacto Individual")
                            with gr.Row():
                                manual_name_in = gr.Textbox(label="Nombre")
                                manual_company_in = gr.Textbox(label="Empresa")
                            with gr.Row():
                                manual_email_in = gr.Textbox(label="Email")
                                manual_phone_in = gr.Textbox(label="Teléfono")
                            with gr.Row():
                                manual_web_in = gr.Textbox(label="Sitio Web")
                                manual_city_in = gr.Textbox(label="Ciudad")
                                manual_country_in = gr.Textbox(label="País")
                            with gr.Row():
                                manual_product_in = gr.Textbox(label="Producto Target (e.g. TravelorHub, Evinra)")
                                manual_notes_in = gr.TextArea(label="Notas / Historial")
                            
                            manual_add_btn = gr.Button("Agregar Contacto", variant="primary")
                            manual_status_out = gr.Textbox(label="Resultado", interactive=False)
                            
                        with gr.TabItem("Importar CSV"):
                            gr.Markdown("#### Cargar Lista de Contactos (CSV)")
                            csv_template_display = gr.TextArea(
                                label="Plantilla CSV (Nombre de columnas exacto)", 
                                value=prodev_manager.get_csv_template(), 
                                interactive=False, 
                                lines=5
                            )
                            with gr.Row():
                                csv_paste_in = gr.TextArea(
                                    label="Pegar contenido CSV aquí", 
                                    placeholder="Nombre,Empresa,Email,Telefono,Sitio Web,Ciudad,Pais,Ultimo Contacto,Producto Usado,Notas...",
                                    lines=8
                                )
                                csv_file_in = gr.File(
                                    label="O subir archivo CSV", 
                                    file_types=[".csv"]
                                )
                            
                            csv_import_btn = gr.Button("Importar Contactos", variant="primary")
                            csv_status_out = gr.TextArea(label="Log de Importación", interactive=False, lines=6)

            with gr.Row():
                clear_db_btn = gr.Button("🗑️ Clear Database", variant="stop")
                stop_server_btn = gr.Button("🛑 Stop Server", variant="stop")

        with gr.Column(scale=1):
            # All Leads and Logs in second column
            gr.Markdown("### 👥 All Leads (Paginated)")
            with gr.Row():
                persona_filter_ui = gr.Dropdown(
                    label="Filtrar por Persona",
                    choices=[
                        ("Todas", "All"), 
                        ("Evinra — Operadores de Eventos", "evinra_events"), 
                        ("TravelorHub — Operadores de Transporte", "travelorhub_transport"), 
                        ("Custom Dev — SMB Operacional", "custom_dev_smb"), 
                        ("Custom Dev — Founders", "custom_dev_founders"), 
                        ("Clientes Antiguos", "old_client"), 
                        ("Sin clasificar (General)", "sin_clasificar")
                    ],
                    value="All",
                    interactive=True
                )
                product_filter_ui = gr.Dropdown(
                    label="Filtrar por Producto Target",
                    choices=[
                        ("Todos", "All"), 
                        ("Evinra", "Evinra"), 
                        ("TravelorHub", "TravelorHub"), 
                        ("Custom Dev", "Custom Dev"), 
                        ("Sin clasificar (Ninguno)", "sin_clasificar")
                    ],
                    value="All",
                    interactive=True
                )
            leads_table = gr.Dataframe(
                headers=["Name", "Email", "Phone", "Event", "Source/Url", "Persona", "Product", "Status"],
                datatype=["str", "str", "str", "str", "str", "str", "str", "str"],
                column_count=(8, "fixed"),
                interactive=False,
                elem_classes="selectable-table"
            )
            with gr.Row():
                prev_page_btn = gr.Button("◀ Previous")
                page_info = gr.Markdown("Page 1 of 1")
                next_page_btn = gr.Button("Next ▶")
            refresh_btn = gr.Button("Refresh Dashboard")

            # Logs moved below table
            gr.Markdown("### 📜 Activity Logs")
            with gr.Row():
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
    
    def auto_refresh(level, page, persona, product):
        """Called by timer - returns dashboard data + updates timer active state."""
        s, st, tbl, logs, p_info, p_num, btn_upd = refresh_dashboard(level, page, persona, product)
        is_running = (AGENT_STATUS == "Running")
        return s, st, tbl, logs, p_info, p_num, btn_upd, gr.Timer(active=is_running)

    live_timer.tick(
        fn=auto_refresh,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn, live_timer]
    )

    # Wire up events
    refresh_btn.click(
        fn=refresh_dashboard,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    # Filter change events
    persona_filter_ui.change(
        fn=refresh_dashboard,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    product_filter_ui.change(
        fn=refresh_dashboard,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    def go_prev_page(level, page, persona, product):
        return refresh_dashboard(level, page - 1, persona, product)
        
    def go_next_page(level, page, persona, product):
        return refresh_dashboard(level, page + 1, persona, product)
        
    prev_page_btn.click(
        fn=go_prev_page,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    next_page_btn.click(
        fn=go_next_page,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    # Wrapper for clear DB
    def clear_db_wrapper(level, page, persona, product):
        res = clear_db_action(level, page, persona, product)
        if isinstance(res, tuple) and len(res) == 2:
            msg, dashboard_data = res
            return msg, *dashboard_data
        return res
        
    clear_db_btn.click(
        fn=clear_db_wrapper,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )

    def clear_logs_wrapper(level, page, persona, product):
        res = clear_logs_action(level, page, persona, product)
        if isinstance(res, tuple) and len(res) == 2:
            msg, dashboard_data = res
            return msg, *dashboard_data
        return res

    clear_logs_btn.click(
        fn=clear_logs_wrapper,
        inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn]
    )
    
    stop_server_btn.click(
        fn=stop_server_action,
        inputs=None,
        outputs=None
    )
    
    # Niche management wire-up
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

    # Standard Niche trigger wrapper
    def trigger_wrapper(start_date, end_date, criteria, max_res, level, page, persona, product, sync_mc):
        msg = manual_trigger(start_date, end_date, criteria, max_res, sync_mailchimp=sync_mc)
        s, st, tbl, logs, p_info, p_num, btn_upd = refresh_dashboard(level, page, persona, product)
        return msg, s, st, tbl, logs, p_info, p_num, btn_upd, gr.Timer(active=True)
        
    trigger_btn.click(
        fn=trigger_wrapper,
        inputs=[start_date_input, end_date_input, search_criteria_input, max_results_input, log_filter, current_page, persona_filter_ui, product_filter_ui, sync_mailchimp_checkbox],
        outputs=[trigger_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn, live_timer]
    )

    # --- Wire up Persona tab events ---
    persona_selector.change(
        fn=on_persona_select,
        inputs=[persona_selector],
        outputs=[persona_product_ui, persona_criteria_ui, persona_queries_display, persona_queries_display, save_queries_btn, prodev_run_btn]
    )
    
    save_queries_btn.click(
        fn=on_save_queries,
        inputs=[persona_selector, persona_queries_display],
        outputs=[queries_save_status]
    )

    # Wire up ProDev targeted search runner
    prodev_run_btn.click(
        fn=prodev_trigger_wrapper,
        inputs=[persona_selector, prodev_extra_criteria, prodev_max_res, log_filter, current_page, persona_filter_ui, product_filter_ui, sync_mailchimp_checkbox],
        outputs=[prodev_status_output, status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn, live_timer]
    )

    # --- Wire up Old Clients events ---
    manual_add_btn.click(
        fn=on_add_manual_contact,
        inputs=[
            manual_name_in, manual_company_in, manual_email_in, manual_phone_in,
            manual_web_in, manual_city_in, manual_country_in, manual_product_in, manual_notes_in
        ],
        outputs=[manual_status_out]
    )
    
    csv_import_btn.click(
        fn=on_import_csv,
        inputs=[csv_paste_in, csv_file_in],
        outputs=[csv_status_out]
    )

    def load_niches_for_ui():
        return gr.Dropdown(choices=active_niches)

    # Initialize components on load
    demo.load(refresh_dashboard, inputs=[log_filter, current_page, persona_filter_ui, product_filter_ui], outputs=[status_panel, stats_panel, leads_table, log_display, page_info, current_page, trigger_btn])
    demo.load(load_niches_for_ui, inputs=[], outputs=[niche_list_ui])
    
    # Initialize persona details on load
    def init_persona():
        choices = prodev_manager.build_gradio_persona_choices()
        if choices:
            first_key = choices[0][1]
            return first_key, *on_persona_select(first_key)[:3]
        return None, "", "", ""
        
    demo.load(
        fn=init_persona,
        inputs=[],
        outputs=[persona_selector, persona_product_ui, persona_criteria_ui, persona_queries_display]
    )

if __name__ == "__main__":
    logger.info("Starting Event & ProDev Prospecting System...")
    
    # Initialize DB (just creating tables if not exists)
    _ = repository.get_stats() 
    
    # Start background scheduler
    start_scheduler()
    
    # Launch Gradio server
    demo.launch(
        server_name="0.0.0.0", 
        server_port=7860, 
        share=False,
        css=custom_css
    )
