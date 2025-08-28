# scheduler_runner.py
import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client
from croniter import croniter

# Import our custom modules
import database_scheduler
import services
import config # Assumes you have a config.py with SUPABASE_URL, SUPABASE_KEY etc.

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Initialize Supabase Client ---
try:
    supabase_url = config.SUPABASE_URL

    supabase: Client = create_client(supabase_url, supabase_key)
    logging.info("Supabase client initialized successfully.")
except Exception as e:
    logging.critical(f"Failed to initialize Supabase client: {e}")
    exit(1)


def process_schedule(schedule: dict):
    """Processes a single due schedule."""
    logging.info(f"Processing schedule ID: {schedule['id']} for user: {schedule['user_id']}")
    action_type = schedule.get('action_type')
    user_id = schedule.get('user_id')
    payload = schedule.get('action_payload', {})

    # --- Action Execution Logic ---
    phone_number = database_scheduler.get_user_phone_by_id(supabase, user_id)
    if not phone_number:
        logging.error(f"Could not find phone number for user {user_id}. Skipping schedule.")
        # Mark as failed to avoid retrying indefinitely
        database_scheduler.update_schedule(supabase, schedule['id'], {'status': 'failed', 'error_message': 'User phone not found'})
        return

    if action_type == 'send_notification':
        message = payload.get('message', 'You have a scheduled reminder.')
        services.send_fonnte_message(phone_number, message)

    elif action_type == 'create_task':
        task = database_scheduler.create_task_from_schedule(supabase, user_id, payload)
        if task:
            confirmation = f"I've created a new task for you: '{task.get('title')}'"
            services.send_fonnte_message(phone_number, confirmation)
        else:
            logging.error(f"Failed to create task from schedule {schedule['id']}")

    elif action_type == 'daily_summary':
        user_timezone = schedule.get('timezone', 'UTC')
        summary_data = database_scheduler.get_daily_summary_data(supabase, user_id, user_timezone)
        summary_message = database_scheduler.format_daily_summary_message(summary_data)
        services.send_fonnte_message(phone_number, summary_message)

    elif action_type == 'execute_prompt':
        # TODO: Implement the logic to call the AI model with the prompt from the payload
        logging.warning(f"Action 'execute_prompt' is not yet implemented. Schedule ID: {schedule['id']}")
        pass

    else:
        logging.error(f"Unknown action type '{action_type}' for schedule ID: {schedule['id']}")
        # Mark as failed
        database_scheduler.update_schedule(supabase, schedule['id'], {'status': 'failed', 'error_message': f'Unknown action type: {action_type}'})
        return

    # --- Post-Execution Schedule Update ---
    if schedule.get('schedule_type') == 'one_time':
        # One-time tasks are completed after running
        update_patch = {'status': 'completed'}
        database_scheduler.update_schedule(supabase, schedule['id'], update_patch)
        logging.info(f"Marked one-time schedule {schedule['id']} as completed.")
    
    elif schedule.get('schedule_type') == 'cron':
        # For recurring tasks, calculate the next run time
        now_utc = datetime.now(timezone.utc)
        cron_str = schedule.get('schedule_value')
        try:
            # croniter helps us find the next scheduled time AFTER the current time
            iter = croniter(cron_str, now_utc)
            next_run_dt = iter.get_next(datetime)
            next_run_iso = next_run_dt.isoformat()
            
            update_patch = {'next_run_at': next_run_iso}
            database_scheduler.update_schedule(supabase, schedule['id'], update_patch)
            logging.info(f"Rescheduled cron job {schedule['id']} to {next_run_iso}.")
        except Exception as e:
            logging.error(f"Failed to calculate next run for cron schedule {schedule['id']}: {e}")
            database_scheduler.update_schedule(supabase, schedule['id'], {'status': 'failed', 'error_message': 'Invalid CRON expression'})


def main():
    """Main function to run the scheduler."""
    logging.info("Scheduler runner started.")
    
    now_utc_iso = datetime.now(timezone.utc).isoformat()
    due_schedules = database_scheduler.get_due_schedules(supabase, now_utc_iso)
    
    if not due_schedules:
        logging.info("No schedules are due.")
        return

    logging.info(f"Found {len(due_schedules)} schedules to process.")
    for schedule in due_schedules:
        try:
            process_schedule(schedule)
        except Exception as e:
            logging.exception(f"An unexpected error occurred while processing schedule {schedule.get('id')}: {e}")
            # Mark schedule as failed to prevent it from running again
            database_scheduler.update_schedule(supabase, schedule['id'], {'status': 'failed', 'error_message': str(e)})

    logging.info("Scheduler run finished.")

if __name__ == "__main__":
    main()