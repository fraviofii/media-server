import requests
import os

from flask import current_app

def get_recordings_path():
    return current_app.config['MEDIAMTX_RECORDINGS_PATH']

def get_mediamtx_api_url():
    return current_app.config['MEDIAMTX_API_URL']

def update_path_recording(path_name, enable_recording):
    """Enable or disable recording for a specific path."""
    url = f"{get_mediamtx_api_url()}/config/paths/patch/{path_name}"
    
    payload = {
        "record": enable_recording,
        "recordPath": f"{get_recordings_path()}/%path/%Y-%m-%d_%H-%M-%S",
        "recordFormat": "fmp4"
    }
    
    try:
        response = requests.patch(url, json=payload)
        response.raise_for_status()
        return True, None
    except requests.exceptions.RequestException as e:
        return False, str(e)

def add_path_to_mediamtx(path_name, enable_recording=False):
    """Adds a new path configuration to Mediamtx via its API."""
    url = f"{get_mediamtx_api_url()}/config/paths/add/{path_name}"
    
    payload = {
        "source": "publisher",
        "record": enable_recording,
        "recordPath": f"{get_recordings_path()}/%path/%Y-%m-%d_%H-%M-%S",
        "recordFormat": "fmp4",
        "recordSegmentDuration": "1h"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return True, None
    except requests.exceptions.RequestException as e:
        return False, str(e)

def get_mediamtx_connections():
    """Gets all active sessions from Mediamtx."""
    try:
        # Fetch list of all paths
        paths_url = f"{get_mediamtx_api_url()}/paths/list"
        paths_response = requests.get(paths_url)
        paths_response.raise_for_status()
        paths_data = paths_response.json().get('items', [])
        
        # Fetch all types of sessions
        session_types = ['rtspsessions', 'webrtcsessions']
        all_sessions = []
        for s_type in session_types:
            url = f"{get_mediamtx_api_url()}/{s_type}/list"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json().get('items', [])
            for dataItem in data:
                all_sessions.append({
                    'id': dataItem.get('id'),
                    'state': dataItem.get('state'),
                    'remoteAddr': dataItem.get('remoteAddr'),
                    'transport': dataItem.get('transport'),
                    'bytesReceived': dataItem.get('bytesReceived'),
                    'bytesSent': dataItem.get('bytesSent'),
                    'rtpPacketsReceived': dataItem.get('rtpPacketsReceived'),
                    'rtpPacketsSent': dataItem.get('rtpPacketsSent'),
                    'rtcpPacketsReceived': dataItem.get('rtcpPacketsReceived'),
                    'rtcpPacketsSent': dataItem.get('rtcpPacketsSent'),
                })
        return {'paths': paths_data, 'sessions': all_sessions}, None
    except requests.exceptions.RequestException as e:
        return None, str(e)

def get_mediamtx_recordings():
    """Gets a list of available recordings from Mediamtx."""
    url = f"{get_mediamtx_api_url()}/recordings/list"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get('items', []), None
    except requests.exceptions.RequestException as e:
        return None, str(e)
    
def update_path_recording_settings(path_name, enable_recording=None, segment_duration=None):
    """Update recording settings for a specific path with optional parameters."""
    url = f"{get_mediamtx_api_url()}/config/paths/patch/{path_name}"
    
    # Build payload with only the parameters that are provided
    payload = {}
    
    if enable_recording is not None:
        payload["record"] = enable_recording
        payload["recordPath"] = f"{get_recordings_path()}/%path/%Y-%m-%d_%H-%M-%S"
        payload["recordFormat"] = "fmp4"
    
    if segment_duration is not None:
        payload["recordSegmentDuration"] = segment_duration
    
    # If no parameters provided, return error
    if not payload:
        return False, "No parameters provided"
    
    try:
        response = requests.patch(url, json=payload)
        response.raise_for_status()
        return True, None
    except requests.exceptions.RequestException as e:
        return False, str(e)

def validate_segment_duration(duration_str):
    """Validate segment duration format (e.g., '30m', '1h', '2h30m')."""
    import re
    
    # Pattern to match valid duration formats
    pattern = r'^(\d+h)?(\d+m)?(\d+s)?$'
    
    if not duration_str or not re.match(pattern, duration_str):
        return False
    
    # Check if at least one unit is provided
    if not any(unit in duration_str for unit in ['h', 'm', 's']):
        return False
    
    return True