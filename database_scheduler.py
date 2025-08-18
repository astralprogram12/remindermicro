# database_scheduler.py

from supabase import Client
from datetime import datetime, date, timedelta
import uuid

# --- Database Functions Required by the Scheduler Service ---

def get_user_phone_by_id(supabase: Client, user_id: str) -> str | None:
    """
    Fetches a user's primary phone number using their user_id.
    This is required to send them messages.
    """
    try:
        res = supabase.table('user_whatsapp').select('phone').eq('user_id', user_id).limit(1).execute()
        return res.data[0].get('phone') if res.data else None
    except Exception as e:
        print(f"!!! DB SCHEDULER ERROR in get_user_phone_by_id: {e}")
        return None

def get_task_context_for_summary(supabase: Client, user_id: str) -> list:
    """
    Fetches a simple list of task titles and statuses for the summary action.
    This is a leaner version than the one used for the AI context.
    """
    try:
        tasks_res = supabase.table('tasks').select(
            'title, status'
        ).eq('user_id', user_id).order('created_at', desc=True).limit(100).execute()
        
        return tasks_res.data or []
    except Exception as e:
        print(f"!!! DB SCHEDULER ERROR in get_task_context_for_summary: {e}")
        return []

def add_task_entry(supabase: Client, user_id: str, **kwargs):
    """
    Inserts a new task into the database.
    Used by the 'create_recurring_task' scheduled action.
    """
    try:
        kwargs['user_id'] = user_id
        res = supabase.table("tasks").insert(kwargs).execute()
        if getattr(res, "error", None): raise Exception(str(res.error))
        return (res.data or [None])[0]
    except Exception as e:
        print(f"!!! DB SCHEDULER ERROR in add_task_entry: {e}")
        return None

def log_action(supabase: Client, user_id: str, action_type: str, entity_type: str = None, 
               entity_id: str = None, action_details: dict = None, user_input: str = None,
               success_status: bool = True, error_details: str = None, execution_time_ms: int = None,
               session_id: str = None) -> dict:
    """Logs every scheduler action for analytics and insights."""
    try:
        log_entry = {
            "user_id": user_id,
            "session_id": session_id or str(uuid.uuid4()),
            "action_type": action_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action_details": action_details or {},
            "user_input": user_input,
            "success_status": success_status,
            "error_details": error_details,
            "execution_time_ms": execution_time_ms,
            "created_at": datetime.now().isoformat()
        }
        
        res = supabase.table("action_logs").insert(log_entry).execute()
        if getattr(res, "error", None):
            print(f"!!! DATABASE ERROR in log_action: {res.error}")
            return None
        return (res.data or [None])[0]
    except Exception as e:
        print(f"!!! DATABASE ERROR in log_action: {e}")
        return None

def get_tasks_for_today(supabase: Client, user_id: str) -> list:
    """
    Get tasks that are relevant for today:
    - Tasks due today (due_date = today)
    - Tasks with no deadline (due_date is null)
    """
    try:
        today = date.today().isoformat()
        
        res = supabase.table("tasks").select(
            "id, title, status, due_date, category, difficulty, notes"
        ).eq("user_id", user_id).or_(
            f"due_date.eq.{today},due_date.is.null"
        ).neq("status", "done").order("created_at", desc=False).execute()
        
        return res.data or []
    except Exception as e:
        print(f"!!! DB SCHEDULER ERROR in get_tasks_for_today: {e}")
        return []

def get_completed_tasks_for_today(supabase: Client, user_id: str) -> list:
    """
    Get tasks completed today (status = 'done' and updated_at = today)
    """
    try:
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        
        res = supabase.table("tasks").select(
            "id, title, status, due_date, category, difficulty, updated_at"
        ).eq("user_id", user_id).eq("status", "done").gte(
            "updated_at", today
        ).lt(
            "updated_at", tomorrow
        ).order("updated_at", desc=True).execute()
        
        return res.data or []
    except Exception as e:
        print(f"!!! DB SCHEDULER ERROR in get_completed_tasks_for_today: {e}")
        return []
