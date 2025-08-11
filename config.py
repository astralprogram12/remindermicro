# config.py
import os
from dotenv import load_dotenv


# Supabase Project Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

# Fonnte API Token for sending WhatsApp messages
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN")

# A secret key to protect the cron job endpoint from public access
CRON_SECRET = os.environ.get("CRON_SECRET")
