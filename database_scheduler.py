# database_scheduler.py

from supabase import Client

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
