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



# --- Application Settings ---

# Usage limits for the WhatsApp bot
UNVERIFIED_LIMIT = 10  # Lifetime message limit for numbers not registered
VERIFIED_LIMIT = 100   # Daily message limit for verified users
MAX_AGENT_LOOPS = 5 # Safety limit for the agent loop
