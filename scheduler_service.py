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
        actions_executed = handle_due_ai_actions()

        return jsonify({
            "status": "success",
            "reminders_sent": reminders_sent,
            "ai_actions_executed": actions_executed
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
            
            # Log reminder sending attempt
            try:
                db.log_action(
                    supabase=supabase,
                    user_id=task['user_id'],
                    action_type="send_reminder",
                    entity_type="task",
                    entity_id=task['id'],
                    action_details={
                        "task_title": task.get('title'),
                        "message_sent": message,
                        "user_phone": user_phone
                    },
                    success_status=True
                )
            except Exception as log_err:
                print(f"!!! SCHEDULER LOGGING ERROR: {log_err}")
            
            services.send_fonnte_message(user_phone, message)
            
            supabase.table("tasks").update({"reminder_sent": True}).eq("id", task['id']).execute()
            sent_count += 1
    
    print(f"Sent {sent_count} reminder(s).")
    return sent_count

def handle_due_ai_actions():
    """Finds and executes recurring scheduled actions."""
    print("--- Checking for due scheduled actions ---")
    now_utc = datetime.now(timezone.utc)
    
    due_actions_res = supabase.table("ai_actions") \
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
            
            # Log summarize_tasks action
            try:
                db.log_action(
                    supabase=supabase,
                    user_id=job['user_id'],
                    action_type="ai_action_summarize_tasks",
                    entity_type="ai_action",
                    entity_id=job['id'],
                    action_details={
                        "job_description": job.get('description'),
                        "outstanding_count": len(outstanding),
                        "message_sent": message
                    },
                    success_status=True
                )
            except Exception as log_err:
                print(f"!!! SCHEDULER LOGGING ERROR: {log_err}")
            
            services.send_fonnte_message(user_phone, message)

        elif action_type == "create_recurring_task":
            title = payload.get("title")
            if title:
                new_task = db.add_task_entry(supabase, job['user_id'], title=title, notes=payload.get("notes")) # <-- UPDATED
                
                # Log create_recurring_task action
                try:
                    db.log_action(
                        supabase=supabase,
                        user_id=job['user_id'],
                        action_type="ai_action_create_task",
                        entity_type="ai_action",
                        entity_id=job['id'],
                        action_details={
                            "job_description": job.get('description'),
                            "task_title": title,
                            "task_notes": payload.get("notes"),
                            "created_task_id": new_task.get('id') if new_task else None
                        },
                        success_status=bool(new_task)
                    )
                except Exception as log_err:
                    print(f"!!! SCHEDULER LOGGING ERROR: {log_err}")
                
                services.send_fonnte_message(user_phone, f"✅ I've just created your scheduled task: '{title}'")

        elif action_type == "task_for_day":
            today_tasks = db.get_tasks_for_today(supabase, job['user_id'])
            
            if not today_tasks:
                message = "🌟 Amazing! You have a clean slate today! No urgent tasks or deadlines. Perfect time to focus on what truly matters!"
            else:
                task_count = len(today_tasks)
                if task_count == 1:
                    intro = "🎯 **Focus Day!** You have one key task today:"
                elif task_count <= 3:
                    intro = f"💪 **Power Day!** You've got {task_count} important tasks:"
                else:
                    intro = f"🚀 **Action Day!** {task_count} tasks ready for your attention:"
                
                task_list = "\n".join([f"• {t['title']}" for t in today_tasks[:5]])  # Limit to 5 for message length
                if task_count > 5:
                    task_list += f"\n... and {task_count - 5} more!"
                
                message = f"{intro}\n\n{task_list}\n\n✨ You've got this! Take them one at a time."
            
            # Log task_for_day action
            try:
                db.log_action(
                    supabase=supabase,
                    user_id=job['user_id'],
                    action_type="ai_action_task_for_day",
                    entity_type="ai_action",
                    entity_id=job['id'],
                    action_details={
                        "job_description": job.get('description'),
                        "tasks_count": len(today_tasks),
                        "message_sent": message
                    },
                    success_status=True
                )
            except Exception as log_err:
                print(f"!!! SCHEDULER LOGGING ERROR: {log_err}")
            
            services.send_fonnte_message(user_phone, message)

        elif action_type == "summary_of_day":
            completed_tasks = db.get_completed_tasks_for_today(supabase, job['user_id'])
            
            if not completed_tasks:
                message = "🌱 Every journey starts with a single step! Progress isn't always about checking boxes. What small win can you celebrate today?"
            else:
                task_count = len(completed_tasks)
                if task_count == 1:
                    intro = "🎉 **Victory!** You completed an important task today:"
                elif task_count <= 3:
                    intro = f"🏆 **Champion!** You crushed {task_count} tasks today:"
                else:
                    intro = f"🚀 **Powerhouse!** You demolished {task_count} tasks today:"
                
                task_list = "\n".join([f"✅ {t['title']}" for t in completed_tasks[:5]])  # Limit to 5 for message length
                if task_count > 5:
                    task_list += f"\n... and {task_count - 5} more!"
                
                message = f"{intro}\n\n{task_list}\n\n🎆 Outstanding work! You're building incredible momentum!"
            
            # Log summary_of_day action
            try:
                db.log_action(
                    supabase=supabase,
                    user_id=job['user_id'],
                    action_type="ai_action_summary_of_day",
                    entity_type="ai_action",
                    entity_id=job['id'],
                    action_details={
                        "job_description": job.get('description'),
                        "completed_count": len(completed_tasks),
                        "message_sent": message
                    },
                    success_status=True
                )
            except Exception as log_err:
                print(f"!!! SCHEDULER LOGGING ERROR: {log_err}")
            
            services.send_fonnte_message(user_phone, message)

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
        supabase.table("ai_actions").update(update_payload).eq("id", job['id']).execute()
    else:
        final_status = "completed" if status == "success" else "error"
        supabase.table("ai_actions").update({"status": final_status}).eq("id", job['id']).execute()


