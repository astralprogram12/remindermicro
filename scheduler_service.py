# scheduler_service.py

import os
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, timezone
import traceback
from croniter import croniter
import google.generativeai as genai
from typing import Dict
# Local imports
import config
import services  # Assuming this has send_fonnte_message
import database_scheduler as db

app = Flask(__name__)

# --- Initialization ---
if not all([config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, config.FONNTE_TOKEN, config.CRON_SECRET, config.GEMINI_API_KEY]):
    raise ValueError("One or more required environment variables are missing.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
genai.configure(api_key=config.GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-2.5-flash')

# --- The Action Executor Class ---
class ActionExecutor:
    """
    This class is responsible for executing the specific action defined
    in a schedule record from the database.
    """
    def __init__(self, supabase_client: Client, ai_model_instance):
        self.supabase = supabase_client
        self.ai_model = ai_model_instance

    def execute(self, schedule: Dict):
        action_type = schedule.get('action_type')
        
        # A simple router to call the correct method based on the action type.
        if action_type == 'send_notification':
            self._execute_send_notification(schedule)
        elif action_type == 'create_task':
            self._execute_create_task(schedule)
        elif action_type == 'execute_prompt':
            self._execute_ai_prompt(schedule)
        else:
            print(f"Unknown action type: {action_type}")

    def _execute_send_notification(self, schedule: Dict):
        user_phone = db.get_user_phone_by_id(self.supabase, schedule['user_id'])
        if not user_phone: 
            print(f"Skipping notification for user {schedule['user_id']}: No phone number found.")
            return

        message = schedule.get('action_payload', {}).get('message', 'You have a scheduled reminder.')
        
        # --- MODIFIED BLOCK ---
        success = services.send_fonnte_message(user_phone, f"🔔 Reminder: {message}")
        if success:
            print(f"Message successfully queued for sending to user {schedule['user_id']}.")
        else:
            print(f"Failed to send notification for schedule {schedule['id']}. See service error above.")
    def _execute_create_task(self, schedule: Dict):
        user_phone = db.get_user_phone_by_id(self.supabase, schedule['user_id'])
        # It's okay if user_phone is None here, we can still create the task
        
        payload = schedule.get('action_payload', {})
        new_task = db.create_task_from_schedule(self.supabase, schedule['user_id'], payload)
        
        if new_task:
            title = new_task.get('title')
            print(f"Created scheduled task '{title}' for user {schedule['user_id']}")
            if user_phone: # Only try to send a message if a phone number exists
                services.send_fonnte_message(user_phone, f"✅ I've just created your scheduled task: '{title}'")
        else:
            print(f"Failed to create scheduled task for user {schedule['user_id']}")
            if user_phone:
                services.send_fonnte_message(user_phone, "⚠️ I tried to create a scheduled task for you, but something went wrong.")
    def _execute_ai_prompt(self, schedule: Dict):
        user_phone = db.get_user_phone_by_id(self.supabase, schedule['user_id'])
        if not user_phone: return

        prompt = schedule.get('action_payload', {}).get('prompt')
        if not prompt:
            print(f"Execute prompt for user {schedule['user_id']} failed: No prompt in payload.")
            return
        
        try:
            print(f"Executing AI prompt for user {schedule['user_id']}...")
            response = self.ai_model.generate_content(prompt)
            services.send_fonnte_message(user_phone, f"🤖 Here is your scheduled AI response:\n\n{response.text}")
            print(f"Sent AI prompt response to user {schedule['user_id']}")
        except Exception as e:
            print(f"AI prompt execution failed for user {schedule['user_id']}: {e}")
            services.send_fonnte_message(user_phone, "⚠️ I tried to run your scheduled AI action, but an error occurred.")

# --- The Main Cron Job Endpoint ---
@app.route('/api/run-schedules', methods=['POST'])
def run_schedules_endpoint():
    # 1. Secure the endpoint
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {config.CRON_SECRET}":
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    print(f"\n--- SCHEDULER TRIGGERED at {datetime.now(timezone.utc).isoformat()} ---")
    
    try:
        executed_count = handle_due_schedules()
        return jsonify({"status": "success", "schedules_executed": executed_count}), 200
    except Exception as e:
        print(f"!!! AN UNEXPECTED ERROR OCCURRED IN SCHEDULER: {e}")
        traceback.print_exc()
        return jsonify({"status": "internal_server_error", "message": str(e)}), 500

def handle_due_schedules():
    """Finds and executes all due scheduled actions from the new unified table."""
    now_utc = datetime.now(timezone.utc)
    
    due_schedules = db.get_due_schedules(supabase, now_utc.isoformat())
    if not due_schedules:
        print("No due schedules found.")
        return 0

    print(f"Found {len(due_schedules)} due schedule(s).")
    executor = ActionExecutor(supabase, ai_model)
    
    for schedule in due_schedules:
        try:
            print(f"Processing schedule {schedule['id']} of type '{schedule['action_type']}'...")
            executor.execute(schedule)
            reschedule_or_complete_job(schedule, now_utc)
        except Exception as e:
            print(f"!!! FAILED to process schedule {schedule['id']}: {e}")
            db.update_schedule(supabase, schedule['id'], {"status": "failed"})

    return len(due_schedules)

def reschedule_or_complete_job(schedule: dict, now_utc: datetime):
    """Calculates the next run time for a recurring job or completes a one-time job."""
    if schedule['schedule_type'] == 'cron':
        try:
            # Use croniter to find the next occurrence from the current time.
            cron_rule = schedule['schedule_value']
            iterator = croniter(cron_rule, now_utc)
            next_run_utc = iterator.get_next(datetime)

            update_payload = {"next_run_at": next_run_utc.isoformat(), "last_run_at": now_utc.isoformat()}
            db.update_schedule(supabase, schedule['id'], update_payload)
            print(f"Rescheduled job {schedule['id']}. Next run at: {next_run_utc.isoformat()}")
        except Exception as e:
            print(f"!!! FAILED to reschedule job {schedule['id']}: {e}")
            db.update_schedule(supabase, schedule['id'], {"status": "failed"})
    else: # 'one_time'
        db.update_schedule(supabase, schedule['id'], {"status": "completed", "last_run_at": now_utc.isoformat()})
        print(f"Completed one-time job {schedule['id']}.")

if __name__ == '__main__':
    # This allows running the Flask app locally for testing.
    # For production, use a proper WSGI server like Gunicorn.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))