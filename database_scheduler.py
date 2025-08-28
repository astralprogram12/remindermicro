# database_scheduler.py
import logging
from supabase import Client
from typing import Dict, List, Any, Union
from datetime import datetime, time, timezone

logger = logging.getLogger(__name__)

# --- Core Schedule Functions ---

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

def update_schedule(supabase: Client, schedule_id: str, patch: Dict) -> None:
    """Updates a schedule record with new data (e.g., new status or next_run_at)."""
    try:
        supabase.table("scheduled_actions").update(patch).eq("id", schedule_id).execute()
        logger.info(f"Successfully updated schedule {schedule_id}")
    except Exception as e:
        logger.error(f"DB Error updating schedule {schedule_id}: {e}")

# --- User and Task Related Functions ---

def get_user_phone_by_id(supabase: Client, user_id: str) -> Union[str, None]:
    """Fetches a user's primary phone number using their user_id."""
    try:
        res = supabase.table('user_whatsapp').select('phone').eq('user_id', user_id).limit(1).execute()
        return res.data[0].get('phone') if res.data else None
    except Exception as e:
        logger.error(f"DB SCHEDULER ERROR in get_user_phone_by_id: {e}")
        return None

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

# --- NEW: Daily Summary Functions ---

def get_daily_summary_data(supabase: Client, user_id: str, user_timezone_str: str = 'UTC') -> Dict[str, Any]:
    """
    Fetches all non-completed tasks and active schedules for the day for a user.
    """
    try:
        # Get the correct timezone object, default to UTC if invalid
        user_tz = timezone(user_timezone_str)
    except Exception:
        user_tz = timezone.utc

    today = datetime.now(user_tz).date()
    start_of_day_utc = datetime.combine(today, time.min, tzinfo=user_tz).astimezone(timezone.utc)
    end_of_day_utc = datetime.combine(today, time.max, tzinfo=user_tz).astimezone(timezone.utc)

    try:
        # 1. Fetch all tasks with a status other than 'done'
        tasks_res = supabase.table("tasks") \
            .select("title, due_date, category") \
            .eq("user_id", user_id) \
            .neq("status", "done") \
            .execute()
        tasks = tasks_res.data if tasks_res.data else []

        # 2. Fetch all active schedules that will run today
        schedules_res = supabase.table("scheduled_actions") \
            .select("action_payload, schedule_value") \
            .eq("user_id", user_id) \
            .eq("status", "active") \
            .gte("next_run_at", start_of_day_utc.isoformat()) \
            .lte("next_run_at", end_of_day_utc.isoformat()) \
            .execute()
        schedules = schedules_res.data if schedules_res.data else []

        return {"tasks": tasks, "schedules": schedules}

    except Exception as e:
        logger.error(f"DB Error fetching daily summary for user {user_id}: {e}")
        return {"tasks": [], "schedules": []}

def format_daily_summary_message(summary_data: Dict[str, Any]) -> str:
    """Formats the tasks and schedules into a readable string message."""
    message_parts = ["*Your Daily Summary* 🗓️\n"]

    # --- Format Tasks ---
    tasks = summary_data.get("tasks", [])
    if tasks:
        message_parts.append("*Pending Tasks:*")
        tasks_by_date = {}
        for task in tasks:
            due_date = task.get('due_date', 'No Due Date')
            if due_date not in tasks_by_date: tasks_by_date[due_date] = []
            tasks_by_date[due_date].append(task)

        for due_date in sorted(tasks_by_date.keys()):
            message_parts.append(f"\n*Due: {due_date}*")
            for task in tasks_by_date[due_date]:
                category = f" [{task['category']}]" if task.get('category') else ""
                message_parts.append(f"- {task['title']}{category}")
    else:
        message_parts.append("✅ You have no pending tasks!")

    # --- Format Schedules for Today ---
    schedules = summary_data.get("schedules", [])
    if schedules:
        message_parts.append("\n\n*Scheduled For Today:*")
        for schedule in schedules:
            payload = schedule.get('action_payload', {})
            item_name = payload.get('message', payload.get('title', 'a scheduled action'))
            message_parts.append(f"- {item_name}")

    return "\n".join(message_parts)