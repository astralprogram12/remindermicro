# services.py
import requests
import config

def send_fonnte_message(phone_number: str, message: str):
    """Sends a message using the Fonnte API."""
    if not config.FONNTE_TOKEN:
        print("!!! SERVICE ERROR: FONNTE_TOKEN is not set. Cannot send message.")
        return

    url = "https://api.fonnte.com/send"
    headers = {
        'Authorization': config.FONNTE_TOKEN
    }
    payload = {
        'target': phone_number,
        'message': message,
        'countryCode': '62',  # Assuming Indonesian country code
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        print(f"Successfully sent message to {phone_number}. Response: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"!!! SERVICE ERROR: Failed to send message to {phone_number}. Error: {e}")
