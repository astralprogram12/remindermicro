# app.py
import os
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, timezone
import traceback

import config
import services

app = Flask(__name__)

# --- Initialization ---
# Ensure all required secrets are loaded before proceeding
if not all([config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, config.FONNTE_TOKEN, config.CRON_SECRET]):
    raise ValueError("One or more required environment variables are missing.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


# --- The Cron Job Endpoint (Corrected Version) ---
@app.route('/api/send-reminders', methods=['POST'])
def send_reminders_route():
    # 1. Secure the endpoint (no changes here)
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {config.CRON_SECRET}":
        print("!!! UNAUTHORIZED ATTEMPT to access /api/send-reminders")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    print("--- CRON JOB TRIGGERED: Checking for due reminders ---")
    
    try:
        # --- QUERY STEP 1: Find all due tasks ---
        now_utc = datetime.now(timezone.utc).isoformat()
        
        due_tasks_res = supabase.table("tasks") \
            .select("id, description, user_id") \
            .lte("reminder_at", now_utc) \
            .eq("reminder_sent", False) \
            .execute()

        if due_tasks_res.data is None:
             print(f"Database query failed: {getattr(due_tasks_res, 'error', 'Unknown error')}")
             return jsonify({"status": "error", "message": "Failed to query tasks"}), 500

        if not due_tasks_res.data:
            print("No due reminders found.")
            return jsonify({"status": "success", "message": "No due reminders."}), 200

        print(f"Found {len(due_tasks_res.data)} reminder(s) to send.")

        # --- STEP 2: Loop through tasks, get phone number for each, send, and update ---
        for task in due_tasks_res.data:
            user_id = task.get('user_id')
            if not user_id:
                continue # Skip if task somehow has no user_id

            # --- QUERY STEP 2a: Get the user's phone number using the user_id ---
            phone_res = supabase.table("user_whatsapp") \
                .select("phone") \
                .eq("user_id", user_id) \
                .execute()

            # Safety check: if we can't find a phone, skip to the next task
            if not phone_res.data:
                print(f"Could not find phone number for user_id {user_id}. Skipping task {task['id']}.")
                continue

            user_phone = phone_res.data[0]['phone']
            message = f"🔔 Reminder: {task['description']}"
            
            print(f"Sending reminder for task ID {task['id']} to phone {user_phone}")
            services.send_fonnte_message(user_phone, message)
            
            # --- STEP 3: CRITICAL: Mark the reminder as sent to avoid spamming ---
            supabase.table("tasks") \
                .update({"reminder_sent": True}) \
                .eq("id", task['id']) \
                .execute()

        return jsonify({"status": "success", "sent_count": len(due_tasks_res.data)}), 200

    except Exception as e:
        print(f"!!! AN UNEXPECTED ERROR OCCURRED IN CRON JOB: {e}")
        traceback.print_exc()
        return jsonify({"status": "internal_server_error"}), 500
