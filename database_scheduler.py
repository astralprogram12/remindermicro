# database_scheduler.py
import logging
from supabase import Client
from typing import Dict, List, Any, Union # <-- Import Union

logger = logging.getLogger(__name__)

def get_due_schedules(supabase: Client, now_utc_iso: str) -> List[Dict[str, Any]]:
    """Fetches all active schedules that are due to run."""
    try:
        res = supabase.table("scheduled_actions") \
            .select("*") \
            .lte("next_run_at", now_utc_iso) \
            .eq("status", "active") \
            .execute()
        return res.data if res.data else []
    except Exception as e:
        logger.error(f"DB Error fetching due schedules: {e}")
        return []

# V-- CORRECTED RETURN TYPE
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

# V-- CORRECTED RETURN TYPE
def create_task_from_schedule(supabase: Client, user_id: str, payload: Dict) -> Union[Dict, None]:
    """Creates a new task entry from a schedule's payload."""
    try:
        task_data = {
            "user_id": user_id,
            "title": payload.get("title", "Scheduled Task"),
            "description": payload.get("description"),
            "notes": payload.get("notes"),
            "category": payload.get("category", "scheduled"),
            "priority": payload.get("priority", "medium"),
            "status": "todo"
        }
        res = supabase.table("tasks").insert(task_data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"DB Error creating task for user {user_id}: {e}")
        return None

def update_schedule(supabase: Client, schedule_id: str, patch: Dict) -> None:
    """Updates a schedule record after it has run."""
    try:
        supabase.table("scheduled_actions").update(patch).eq("id", schedule_id).execute()
    except Exception as e:
        logger.error(f"DB Error updating schedule {schedule_id}: {e}")