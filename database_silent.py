# database_silent.py
# Silent Mode Database Operations

from supabase import Client
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import json
import pytz

def create_silent_session(supabase: Client, user_id: str, duration_minutes: int, 
                         trigger_type: str = 'manual') -> Dict[str, Any] | None:
    """Creates a new silent session for a user."""
    try:
        # End any existing active silent sessions first
        end_active_silent_sessions(supabase, user_id, 'system')
        
        data = {
            'user_id': user_id,
            'duration_minutes': duration_minutes,
            'trigger_type': trigger_type,
            'is_active': True,
            'accumulated_actions': [],
            'action_count': 0
        }
        
        result = supabase.table('silent_sessions').insert(data).execute()
        if result.data:
            print(f"Silent session created for user {user_id}, duration: {duration_minutes} minutes")
            return result.data[0]
        return None
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in create_silent_session: {e}")
        return None

def get_active_silent_session(supabase: Client, user_id: str) -> Dict[str, Any] | None:
    """Gets the current active silent session for a user."""
    try:
        result = supabase.table('silent_sessions') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .order('start_time', desc=True) \
            .limit(1) \
            .execute()
        
        if result.data:
            session = result.data[0]
            # Check if session has expired
            start_time = datetime.fromisoformat(session['start_time'].replace('Z', '+00:00'))
            end_time = start_time + timedelta(minutes=session['duration_minutes'])
            
            if datetime.now(timezone.utc) > end_time:
                # Auto-expire the session
                end_silent_session(supabase, session['id'], 'expired')
                return None
                
            return session
        return None
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in get_active_silent_session: {e}")
        return None

def add_action_to_silent_session(supabase: Client, session_id: str, action_data: Dict[str, Any]) -> bool:
    """Adds an action to the accumulated actions in a silent session."""
    try:
        # Get current session
        result = supabase.table('silent_sessions') \
            .select('accumulated_actions, action_count') \
            .eq('id', session_id) \
            .execute()
        
        if not result.data:
            return False
            
        current_actions = result.data[0]['accumulated_actions'] or []
        current_count = result.data[0]['action_count'] or 0
        
        # Add timestamp to action
        action_data['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        # Append new action
        current_actions.append(action_data)
        
        # Update session
        update_result = supabase.table('silent_sessions') \
            .update({
                'accumulated_actions': current_actions,
                'action_count': current_count + 1
            }) \
            .eq('id', session_id) \
            .execute()
        
        return len(update_result.data) > 0
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in add_action_to_silent_session: {e}")
        return False

def end_silent_session(supabase: Client, session_id: str, exit_reason: str = 'manual_exit') -> Dict[str, Any] | None:
    """Ends a silent session and returns the session data."""
    try:
        # Get session data before ending
        session_result = supabase.table('silent_sessions') \
            .select('*') \
            .eq('id', session_id) \
            .execute()
        
        if not session_result.data:
            return None
            
        session_data = session_result.data[0]
        
        # End the session
        result = supabase.table('silent_sessions') \
            .update({
                'is_active': False,
                'end_time': datetime.now(timezone.utc).isoformat(),
                'exit_reason': exit_reason
            }) \
            .eq('id', session_id) \
            .execute()
        
        if result.data:
            print(f"Silent session {session_id} ended with reason: {exit_reason}")
            return session_data
        return None
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in end_silent_session: {e}")
        return None

def end_active_silent_sessions(supabase: Client, user_id: str, exit_reason: str = 'system') -> int:
    """Ends all active silent sessions for a user. Returns count of ended sessions."""
    try:
        result = supabase.table('silent_sessions') \
            .update({
                'is_active': False,
                'end_time': datetime.now(timezone.utc).isoformat(),
                'exit_reason': exit_reason
            }) \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .execute()
        
        count = len(result.data) if result.data else 0
        if count > 0:
            print(f"Ended {count} active silent sessions for user {user_id}")
        return count
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in end_active_silent_sessions: {e}")
        return 0

def get_user_silent_preferences(supabase: Client, user_id: str) -> Dict[str, Any]:
    """Gets user's silent mode preferences."""
    try:
        result = supabase.table('user_whatsapp') \
            .select('auto_silent_enabled, auto_silent_start_hour, auto_silent_end_hour, timezone') \
            .eq('user_id', user_id) \
            .execute()
        
        if result.data:
            prefs = result.data[0]
            return {
                'auto_silent_enabled': prefs.get('auto_silent_enabled', True),
                'start_hour': prefs.get('auto_silent_start_hour', 7),
                'end_hour': prefs.get('auto_silent_end_hour', 11),
                'timezone': prefs.get('timezone', 'UTC')
            }
        
        # Return defaults if no preferences found
        return {
            'auto_silent_enabled': True,
            'start_hour': 7,
            'end_hour': 11,
            'timezone': 'UTC'
        }
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in get_user_silent_preferences: {e}")
        return {'auto_silent_enabled': False, 'start_hour': 7, 'end_hour': 11, 'timezone': 'UTC'}

def update_user_silent_preferences(supabase: Client, user_id: str, **preferences) -> bool:
    """Updates user's silent mode preferences."""
    try:
        valid_fields = ['auto_silent_enabled', 'auto_silent_start_hour', 'auto_silent_end_hour']
        update_data = {k: v for k, v in preferences.items() if k in valid_fields}
        
        if not update_data:
            return False
            
        result = supabase.table('user_whatsapp') \
            .update(update_data) \
            .eq('user_id', user_id) \
            .execute()
        
        return len(result.data) > 0
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in update_user_silent_preferences: {e}")
        return False

def get_expired_silent_sessions(supabase: Client) -> List[Dict[str, Any]]:
    """Gets all expired silent sessions that are still marked as active."""
    try:
        # Use raw SQL for more complex time calculations
        query = """
        SELECT * FROM silent_sessions 
        WHERE is_active = true 
        AND start_time + (duration_minutes || ' minutes')::INTERVAL < NOW()
        ORDER BY start_time ASC
        """
        
        result = supabase.rpc('raw_sql', {'query': query}).execute()
        return result.data if result.data else []
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in get_expired_silent_sessions: {e}")
        return []

def cleanup_old_silent_sessions(supabase: Client, days_old: int = 30) -> int:
    """Cleans up old silent sessions older than specified days."""
    try:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        
        result = supabase.table('silent_sessions') \
            .delete() \
            .lt('start_time', cutoff_date) \
            .eq('is_active', False) \
            .execute()
        
        count = len(result.data) if result.data else 0
        if count > 0:
            print(f"Cleaned up {count} old silent sessions")
        return count
        
    except Exception as e:
        print(f"!!! DATABASE ERROR in cleanup_old_silent_sessions: {e}")
        return 0
