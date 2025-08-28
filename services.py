# services.py

import requests
import config

def send_fonnte_message(phone_number: str, message: str) -> bool: # Add return type hint
    """
    Sends a message using the Fonnte API.
    Returns True on success, False on failure.
    """
    if not config.FONNTE_TOKEN:
        print("!!! SERVICE ERROR: FONNTE_TOKEN is not set. Cannot send message.")
        return False # <-- Return False

    url = "https://api.fonnte.com/send"
    headers = {
        'Authorization': config.FONNTE_TOKEN
    }
    payload = {
        'target': phone_number,
        'message': message,
        'countryCode': '62',
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status() 
        
        # Optional: Check Fonnte's specific response body for success
        response_data = response.json()
        if 'status' in response_data and response_data['status'] is True:
             print(f"Successfully sent message to {phone_number}. Response: {response_data}")
             return True # <-- Return True on success
        else:
             print(f"!!! SERVICE ERROR: Fonnte API indicated failure. Response: {response_data}")
             return False # <-- Return False if Fonnte says it failed

    except requests.exceptions.RequestException as e:
        print(f"!!! SERVICE ERROR: Failed to send message to {phone_number}. Error: {e}")
        # If the response exists, print it for more context (e.g., for 401 Unauthorized)
        if e.response is not None:
            print(f"!!! SERVICE ERROR: Response Body: {e.response.text}")
        return False # <-- Return False on exception