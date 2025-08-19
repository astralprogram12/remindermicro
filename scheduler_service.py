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
import database_silent

app = Flask(__name__)

# --- Initialization ---
if not all([config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, config.FONNTE_TOKEN, config.CRON_SECRET]):
    raise ValueError("One or more required environment variables are missing.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

# --- Helper Functions ---
def generate_simple_silent_mode_summary(session_data: dict) -> str:
    """Generates a simple summary message for ended silent mode sessions."""
    try:
        duration_minutes = session_data.get('duration_minutes', 0)
        action_count = session_data.get('action_count', 0)
        trigger_type = session_data.get('trigger_type', 'unknown')
        accumulated_actions = session_data.get('accumulated_actions', [])
        
        # Convert duration to readable format
        if duration_minutes < 60:
            duration_text = f"{duration_minutes} minute{'s' if duration_minutes != 1 else ''}"
        else:
            hours = duration_minutes // 60
            remaining_minutes = duration_minutes % 60
            if remaining_minutes == 0:
                duration_text = f"{hours} hour{'s' if hours != 1 else ''}"
            else:
                duration_text = f"{hours}h {remaining_minutes}m"
        
        # Create header based on trigger type
        if trigger_type == 'auto':
            header = "🔔 **Auto Silent Mode Ended**"
            intro = f"Your scheduled silent period ({duration_text}) has ended."
        else:
            header = "🔔 **Silent Mode Ended**"
            intro = f"Your {duration_text} silent period has ended."
        
        # Create action summary
        if action_count == 0:
            activity_summary = "\n✨ You had a peaceful time - no activity during silent mode."
        elif action_count == 1:
            activity_summary = "\n📋 **Activity Summary:**\n1 action was processed while you were in silent mode."
        else:
            activity_summary = f"\n📋 **Activity Summary:**\n{action_count} actions were processed while you were in silent mode."
        
        # Add some recent actions if available (limit to 3 most recent)
        if accumulated_actions:
            recent_actions = accumulated_actions[-3:]  # Get last 3 actions
            action_list = []
            for i, action in enumerate(recent_actions, 1):
                action_text = action.get('content', action.get('action_type', 'Unknown action'))
                # Limit action text length
                if len(action_text) > 80:
                    action_text = action_text[:77] + "..."
                action_list.append(f"{i}. {action_text}")
            
            if len(accumulated_actions) > 3:
                activity_summary += f"\n\nLast {len(recent_actions)} actions:"
            else:
                activity_summary += "\n\nActions processed:"
            
            activity_summary += "\n" + "\n".join(action_list)
            
            if len(accumulated_actions) > 3:
                activity_summary += f"\n... and {len(accumulated_actions) - 3} more"
        
        footer = "\n\n🤖 I'm back online and ready to help!"
        
        return f"{header}\n\n{intro}{activity_summary}{footer}"
        
    except Exception as e:
        print(f"!!! ERROR generating silent mode summary: {e}")
        return "🔔 **Silent Mode Ended**\n\nYour silent period has ended. I'm back online and ready to help!"


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
        silent_sessions_managed = handle_daily_silent_mode()
        expired_sessions_ended = handle_expired_silent_sessions()

        return jsonify({
            "status": "success",
            "reminders_sent": reminders_sent,
            "ai_actions_executed": actions_executed,
            "silent_sessions_managed": silent_sessions_managed,
            "expired_sessions_ended": expired_sessions_ended
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

def handle_daily_silent_mode():
    """Handles daily silent mode activation/deactivation based on user preferences."""
    print("--- Checking for daily silent mode management ---")
    
    try:
        from datetime import datetime, timezone, timedelta
        import pytz
        
        managed_count = 0
        now_utc = datetime.now(timezone.utc)
        
        # Get all users with auto silent mode enabled
        users_result = supabase.table("user_whatsapp") \
            .select("user_id, timezone, auto_silent_enabled, auto_silent_start_hour, auto_silent_end_hour") \
            .eq("auto_silent_enabled", True) \
            .execute()
        
        if not users_result.data:
            print("No users with auto silent mode enabled.")
            return 0
        
        for user in users_result.data:
            user_id = user['user_id']
            user_timezone = user.get('timezone', 'UTC')
            start_hour = user.get('auto_silent_start_hour', 7)
            end_hour = user.get('auto_silent_end_hour', 11)
            
            try:
                # Convert UTC time to user's timezone
                tz = pytz.timezone(user_timezone)
                user_time = now_utc.astimezone(tz)
                current_hour = user_time.hour
                
                # Check if we're at the start hour and should activate silent mode
                if current_hour == start_hour:
                    # Check if user already has active silent session
                    active_session = database_silent.get_active_silent_session(supabase, user_id)
                    
                    if not active_session:
                        # Calculate duration until end hour
                        if end_hour > start_hour:
                            duration_hours = end_hour - start_hour
                        else:
                            # Handle case where end hour is next day (e.g., 23:00 to 07:00)
                            duration_hours = (24 - start_hour) + end_hour
                        
                        duration_minutes = duration_hours * 60
                        
                        # Create silent session
                        session = database_silent.create_silent_session(
                            supabase, user_id, duration_minutes, 'auto'
                        )
                        
                        if session:
                            # Send activation notification
                            user_phone = db.get_user_phone_by_id(supabase, user_id)
                            if user_phone:
                                message = f"🔇 **Auto Silent Mode Activated** \n\nI'm now in silent mode from {start_hour:02d}:00 to {end_hour:02d}:00 as per your preferences.\n\nI'll continue processing your requests but won't send replies until {end_hour:02d}:00. You'll get a summary then.\n\n💡 **To exit early:** Send 'exit silent mode'"
                                services.send_fonnte_message(user_phone, message)
                                
                                # Log the activation
                                try:
                                    db.log_action(
                                        supabase=supabase,
                                        user_id=user_id,
                                        action_type="auto_activate_silent_mode",
                                        entity_type="silent_session",
                                        entity_id=session['id'],
                                        action_details={
                                            "start_hour": start_hour,
                                            "end_hour": end_hour,
                                            "duration_minutes": duration_minutes,
                                            "timezone": user_timezone,
                                            "notification_sent": True
                                        },
                                        success_status=True
                                    )
                                except Exception as log_err:
                                    print(f"!!! LOGGING ERROR for auto silent activation: {log_err}")
                            
                            managed_count += 1
                            print(f"Auto-activated silent mode for user {user_id} from {start_hour}:00 to {end_hour}:00")
                
            except Exception as user_err:
                print(f"!!! ERROR processing auto silent mode for user {user_id}: {user_err}")
                continue
        
        return managed_count
        
    except Exception as e:
        print(f"!!! ERROR in handle_daily_silent_mode: {e}")
        traceback.print_exc()
        return 0

def handle_expired_silent_sessions():
    """Ends expired silent sessions and sends summaries."""
    print("--- Checking for expired silent sessions ---")
    
    try:
        ended_count = 0
        
        # Get expired sessions
        expired_sessions = database_silent.get_expired_silent_sessions(supabase)
        
        if not expired_sessions:
            print("No expired silent sessions found.")
            return 0
        
        for session in expired_sessions:
            try:
                # End the session
                session_data = database_silent.end_silent_session(supabase, session['id'], 'expired')
                
                if session_data:
                    ended_count += 1
                    
                    # Generate and send summary
                    user_phone = db.get_user_phone_by_id(supabase, session['user_id'])
                    if user_phone:
                        # Generate summary locally
                        summary = generate_simple_silent_mode_summary(session_data)
                        
                        # Send the summary
                        services.send_fonnte_message(user_phone, summary)
                        
                        # Log the summary sending
                        try:
                            db.log_action(
                                supabase=supabase,
                                user_id=session['user_id'],
                                action_type="send_silent_mode_summary",
                                entity_type="silent_session",
                                entity_id=session['id'],
                                action_details={
                                    "session_duration_minutes": session_data.get('duration_minutes', 0),
                                    "actions_count": session_data.get('action_count', 0),
                                    "trigger_type": session_data.get('trigger_type', 'unknown'),
                                    "summary_sent": True
                                },
                                success_status=True
                            )
                        except Exception as log_err:
                            print(f"!!! LOGGING ERROR for silent mode summary: {log_err}")
                        
                        print(f"Sent silent mode summary to user {session['user_id']} for session {session['id']}")
                    
            except Exception as session_err:
                print(f"!!! ERROR ending expired session {session['id']}: {session_err}")
                continue
        
        return ended_count
        
    except Exception as e:
        print(f"!!! ERROR in handle_expired_silent_sessions: {e}")
        traceback.print_exc()
        return 0


