# scheduler_service.py (Your complete microservice app)

import os
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, timezone
import traceback
import pytz
from croniter import croniter

# Local imports
import config
import services
import database_scheduler as db # <-- THE CHANGE IS HERE

app = Flask(__name__)

# --- Initialization ---
if not all([config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, config.FONNTE_TOKEN, config.CRON_SECRET]):
    raise ValueError("One or more required environment variables are missing.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

# --- The Main Cron Job Endpoint ---
@app.route('/api/run-jobs', methods=['POST'])
def run_all_due_jobs():
    # 1. Secure the endpoint
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {config.CRON_SECRET}":
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    print(f"\n--- CRON JOB TRIGGERED at {datetime.now(timezone.utc).isoformat()} ---")
    
    try:
        # --- Execute Both Types of Jobs ---
        reminders_sent = handle_due_reminders()
        actions_executed = handle_due_scheduled_actions()

        return jsonify({
            "status": "success",
            "reminders_sent": reminders_sent,
            "scheduled_actions_executed": actions_executed
        }), 200

    except Exception as e:
        print(f"!!! AN UNEXPECTED ERROR OCCURRED IN CRON JOB: {e}")
        traceback.print_exc()
        return jsonify({"status": "internal_server_error"}), 500

def handle_due_reminders():
    """Finds and sends one-time task reminders."""
    print("--- Checking for due task reminders ---")
    now_utc = datetime.now(timezone.utc).isoformat()
    
    due_tasks_res = supabase.table("tasks") \
        .select("id, title, user_id") \
        .lte("reminder_at", now_utc) \
        .eq("reminder_sent", False) \
        .execute()

    if not due_tasks_res.data:
        print("No due reminders found.")
        return 0

    sent_count = 0
    for task in due_tasks_res.data:
        user_phone = db.get_user_phone_by_id(supabase, task['user_id']) # <-- UPDATED
        if user_phone:
            message = f"🔔 Reminder: Don't forget to '{task.get('title')}'"
            services.send_fonnte_message(user_phone, message)
            
            supabase.table("tasks").update({"reminder_sent": True}).eq("id", task['id']).execute()
            sent_count += 1
    
    print(f"Sent {sent_count} reminder(s).")
    return sent_count

def handle_due_scheduled_actions():
    """Finds and executes recurring scheduled actions."""
    print("--- Checking for due scheduled actions ---")
    now_utc = datetime.now(timezone.utc)
    
    due_actions_res = supabase.table("scheduled_actions") \
        .select("*") \
        .lte("next_run_at", now_utc.isoformat()) \
        .eq("status", "active") \
        .execute()

    if not due_actions_res.data:
        print("No due scheduled actions found.")
        return 0

    executed_count = 0
    for job in due_actions_res.data:
        print(f"Executing job {job['id']} of type '{job['action_type']}'...")
        user_phone = db.get_user_phone_by_id(supabase, job['user_id']) # <-- UPDATED
        
        if not user_phone:
            update_job_after_run(job, "error")
            continue

        # --- Execute the specific action ---
        action_type = job['action_type']
        payload = job.get('action_payload', {})
        
        if action_type == "summarize_tasks":
            tasks = db.get_task_context_for_summary(supabase, job['user_id']) # <-- UPDATED
            outstanding = [t for t in tasks if t.get("status") != 'done']
            message = "✨ Daily Summary: You have no outstanding tasks!" if not outstanding else f"✨ Daily Summary! You have {len(outstanding)} tasks to do:\n" + "\n".join([f"- {t['title']}" for t in outstanding])
            services.send_fonnte_message(user_phone, message)

        elif action_type == "create_recurring_task":
            title = payload.get("title")
            if title:
                db.add_task_entry(supabase, job['user_id'], title=title, notes=payload.get("notes")) # <-- UPDATED
                services.send_fonnte_message(user_phone, f"✅ I've just created your scheduled task: '{title}'")

        # After execution, reschedule it
        update_job_after_run(job, "success")
        executed_count += 1
        
    print(f"Executed {executed_count} scheduled action(s).")
    return executed_count

def update_job_after_run(job: dict, status: str):
    """Calculates the next run time for a recurring job and updates it."""
    now_utc = datetime.now(timezone.utc)
    if status == "success" and job.get("schedule_spec"):
        user_tz = pytz.timezone(job.get("timezone", "UTC"))
        now_in_user_tz = datetime.now(user_tz)
        
        cron = croniter(job['schedule_spec'], now_in_user_tz)
        next_run_local = cron.get_next(datetime)
        next_run_utc = next_run_local.astimezone(pytz.utc)

        update_payload = { "next_run_at": next_run_utc.isoformat(), "last_run_at": now_utc.isoformat() }
        supabase.table("scheduled_actions").update(update_payload).eq("id", job['id']).execute()
    else:
        final_status = "completed" if status == "success" else "error"
        supabase.table("scheduled_actions").update({"status": final_status}).eq("id", job['id']).execute()

