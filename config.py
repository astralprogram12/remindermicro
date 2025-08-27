import os

# --- Secrets and Configurations ---
# Load secrets from environment variables in production.

# Fonnte API Token for sending WhatsApp messages
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN")

# Google Generative AI API Key for accessing Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# --- Supabase Project Credentials ---
# WARNING: The SERVICE_ROLE_KEY is a secret and should never be exposed in client-side code.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
CRON_SECRET = os.environ.get("CRON_SECRET")
