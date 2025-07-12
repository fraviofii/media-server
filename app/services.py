import requests
import os
import time
from functools import wraps
from flask import current_app

# Simple in-memory cache for serverless
_last_check_time = 0
_check_interval = 30  # Check every 30 seconds at most

def retry_on_failure(max_retries=3, delay=1):
    """Decorator to retry function on failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.RequestException as e:
                    if attempt == max_retries - 1:
                        raise
                    current_app.logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                    time.sleep(delay * (2 ** attempt))  # Exponential backoff
            return None
        return wrapper
    return decorator

def ensure_mediamtx_paths(func):
    """Decorator to ensure MediaMTX paths are in sync before executing the function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        global _last_check_time
        current_time = time.time()
        
        # Only check if enough time has passed since last check
        if current_time - _last_check_time > _check_interval:
            try:
                _check_and_restore_paths()
                _last_check_time = current_time
            except Exception as e:
                current_app.logger.warning(f"Failed to check/restore MediaMTX paths: {str(e)}")
                # Continue with the original function even if path check fails
        
        return func(*args, **kwargs)
    return wrapper

def _check_and_restore_paths():
    """Check if paths are in sync and restore if needed."""
    try:
        # Quick check - is MediaMTX reachable?
        paths_url = f"{get_mediamtx_api_url()}/paths/list"
        response = requests.get(paths_url, timeout=3)  # Short timeout for serverless
        response.raise_for_status()
        
        # Get current paths from MediaMTX
        mediamtx_paths = response.json().get('items', [])
        mediamtx_path_names = [path.get('name') for path in mediamtx_paths]
        
        # Get paths from database
        from app.models import StreamPath
        db_paths = StreamPath.query.all()
        db_path_names = [path.path_name for path in db_paths]
        
        # Find missing paths
        missing_paths = [name for name in db_path_names if name not in mediamtx_path_names]
        
        if missing_paths:
            current_app.logger.info(f"MediaMTX missing paths detected: {missing_paths}")
            restored_count, errors = restore_paths_to_mediamtx()
            current_app.logger.info(f"Auto-restored {restored_count} paths to MediaMTX")
            
            if errors:
                current_app.logger.error(f"Errors during auto-restore: {errors}")
                
    except requests.exceptions.RequestException:
        # MediaMTX is down or unreachable, skip restoration
        current_app.logger.warning("MediaMTX is unreachable, skipping path check")
    except Exception as e:
        current_app.logger.error(f"Error in MediaMTX path check: {str(e)}")

def restore_paths_to_mediamtx():
    """Restore all paths from database to MediaMTX."""
    from app.models import StreamPath
    
    try:
        # Get all paths from database
        paths = StreamPath.query.all()
        
        restored_count = 0
        errors = []
        
        for path in paths:
            success, error = add_path_to_mediamtx(path.path_name, enable_recording=True)
            if success:
                restored_count += 1
                current_app.logger.info(f"Restored path: {path.path_name}")
            else:
                errors.append(f"Failed to restore path '{path.path_name}': {error}")
        
        if errors:
            current_app.logger.warning(f"Some paths failed to restore: {errors}")
        
        current_app.logger.info(f"Restored {restored_count} paths to MediaMTX")
        return restored_count, errors
        
    except Exception as e:
        current_app.logger.error(f"Error restoring paths: {str(e)}")
        return 0, [str(e)]

def check_mediamtx_health():
    """Check if MediaMTX is healthy and paths are in sync."""
    try:
        # Check if MediaMTX API is responding
        paths_url = f"{get_mediamtx_api_url()}/paths/list"
        response = requests.get(paths_url, timeout=5)
        response.raise_for_status()
        
        # Get current paths from MediaMTX
        mediamtx_paths = response.json().get('items', [])
        mediamtx_path_names = [path.get('name') for path in mediamtx_paths]
        
        # Get paths from database
        from app.models import StreamPath
        db_paths = StreamPath.query.all()
        db_path_names = [path.path_name for path in db_paths]
        
        # Find missing paths
        missing_paths = [name for name in db_path_names if name not in mediamtx_path_names]
        
        return {
            'healthy': len(missing_paths) == 0,
            'missing_paths': missing_paths,
            'mediamtx_paths': len(mediamtx_path_names),
            'db_paths': len(db_path_names),
            'mediamtx_reachable': True
        }
        
    except requests.exceptions.RequestException as e:
        return {
            'healthy': False,
            'error': str(e),
            'mediamtx_reachable': False
        }

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

@retry_on_failure(max_retries=3, delay=2)
def add_path_to_mediamtx(path_name, enable_recording=False):
    """Adds a new path configuration to Mediamtx via its API with retry logic."""
    url = f"{get_mediamtx_api_url()}/config/paths/add/{path_name}"
    
    payload = {
        "source": "publisher",
        "record": enable_recording,
        "recordPath": f"{get_recordings_path()}/%path/%Y-%m-%d_%H-%M-%S",
        "recordFormat": "fmp4",
        "recordSegmentDuration": "1h"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
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