import datetime
from flask import Blueprint, request, jsonify, g, current_app
import jwt
import requests

from app import db
from app.models import User, StreamPath
from app.decorators import jwt_required
from app.services import (
    add_path_to_mediamtx,
    get_mediamtx_connections,
    get_mediamtx_recordings,
    update_path_recording,
    get_mediamtx_api_url,
    validate_segment_duration,
    update_path_recording_settings
)

bp = Blueprint('api', __name__)

@bp.route('/auth/login', methods=['POST'])
def login():
    """Authenticates a user and returns a JWT."""
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'message': 'Username and password required'}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not user.check_password(data['password']):
        return jsonify({'message': 'Invalid credentials'}), 401
        
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")
    
    return jsonify({'token': token})

@bp.route('/paths', methods=['GET'])
@jwt_required
def list_paths():
    """Lists all paths created by the authenticated user."""
    user_paths = StreamPath.query.filter_by(user_id=g.current_user.id).all()
    return jsonify([path.to_dict() for path in user_paths])

@bp.route('/paths/new', methods=['POST'])
@jwt_required
def create_path():
    """Creates a new streaming path."""
    data = request.get_json()
    path_name = data.get('path_name')

    if not path_name:
        return jsonify({'message': 'path_name is required'}), 400
    
    if StreamPath.query.filter_by(path_name=path_name).first():
        return jsonify({'message': 'Path name already exists'}), 409
    
    # Add path to Mediamtx first
    success, error = add_path_to_mediamtx(path_name)
    if not success:
        return jsonify({'message': 'Failed to configure media server', 'error': error}), 500

    # If successful, save to our database
    new_path = StreamPath(path_name=path_name, owner=g.current_user)
    db.session.add(new_path)
    db.session.commit()
    
    return jsonify({'message': 'Path created successfully', 'path': new_path.to_dict()}), 201

@bp.route('/connections', methods=['GET'])
@jwt_required
def get_connections():
    """Returns the current state of connections from Mediamtx."""
    connections, error = get_mediamtx_connections()
    if error:
        return jsonify({'message': 'Could not retrieve connections from media server', 'error': error}), 500
    return jsonify(connections)

@bp.route('/recordings', methods=['GET'])
@jwt_required
def list_recordings():
    """Lists all available MP4 recordings."""
    recordings, error = get_mediamtx_recordings()
    if error:
        return jsonify({'message': 'Could not retrieve recordings from media server', 'error': error}), 500
    return jsonify(recordings)

@bp.route('/paths/<path_name>/recording/start', methods=['POST'])
@jwt_required
def start_recording(path_name):
    """Start recording for a specific path."""
    # Check if path exists in database
    stream_path = StreamPath.query.filter_by(path_name=path_name).first()
    if not stream_path:
        return jsonify({'message': 'Path not found'}), 404
    
    # Check if user owns the path
    if stream_path.owner != g.current_user:
        return jsonify({'message': 'Unauthorized'}), 403
    
    # Enable recording via MediaMTX API
    success, error = update_path_recording(path_name, True)
    if not success:
        return jsonify({'message': 'Failed to start recording', 'error': error}), 500
    
    return jsonify({'message': f'Recording started for path {path_name}'}), 200

@bp.route('/paths/<path_name>/recording/stop', methods=['POST'])
@jwt_required
def stop_recording(path_name):
    """Stop recording for a specific path."""
    # Check if path exists in database
    stream_path = StreamPath.query.filter_by(path_name=path_name).first()
    if not stream_path:
        return jsonify({'message': 'Path not found'}), 404
    
    # Check if user owns the path
    if stream_path.owner != g.current_user:
        return jsonify({'message': 'Unauthorized'}), 403
    
    # Disable recording via MediaMTX API
    success, error = update_path_recording(path_name, False)
    if not success:
        return jsonify({'message': 'Failed to stop recording', 'error': error}), 500
    
    return jsonify({'message': f'Recording stopped for path {path_name}'}), 200

@bp.route('/paths/<path_name>/recording/status', methods=['GET'])
@jwt_required
def get_recording_status(path_name):
    """Get recording status for a specific path."""
    # Check if path exists in database
    stream_path = StreamPath.query.filter_by(path_name=path_name).first()
    if not stream_path:
        return jsonify({'message': 'Path not found'}), 404
    
    # Check if user owns the path
    if stream_path.owner != g.current_user:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        # Get path configuration from MediaMTX
        url = f"{get_mediamtx_api_url()}/config/paths/get/{path_name}"
        response = requests.get(url)
        response.raise_for_status()
        path_config = response.json()
        
        recording_enabled = path_config.get('record', False)
        return jsonify({
            'path_name': path_name,
            'recording_enabled': recording_enabled
        }), 200
    except requests.exceptions.RequestException as e:
        return jsonify({'message': 'Failed to get recording status', 'error': str(e)}), 500
    
@bp.route('/paths/<path_name>/recording/settings', methods=['PUT'])
@jwt_required
def update_recording_settings(path_name):
    """Update recording settings for a specific path."""
    # Check if path exists in database
    stream_path = StreamPath.query.filter_by(path_name=path_name).first()
    if not stream_path:
        return jsonify({'message': 'Path not found'}), 404
    
    # Check if user owns the path
    if stream_path.owner != g.current_user:
        return jsonify({'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    
    # Extract parameters from request
    enable_recording = data.get('enable_recording')
    segment_duration = data.get('segment_duration')
    
    # Validate segment duration if provided
    if segment_duration is not None:
        if not validate_segment_duration(segment_duration):
            return jsonify({
                'message': 'Invalid segment duration format. Use format like "30m", "1h", "2h30m"'
            }), 400
    
    # Update recording settings
    success, error = update_path_recording_settings(
        path_name, 
        enable_recording=enable_recording, 
        segment_duration=segment_duration
    )
    
    if not success:
        return jsonify({'message': 'Failed to update recording settings', 'error': error}), 500
    
    response_data = {'message': f'Recording settings updated for path {path_name}'}
    
    # Add details about what was updated
    if enable_recording is not None:
        response_data['recording_enabled'] = enable_recording
    if segment_duration is not None:
        response_data['segment_duration'] = segment_duration
    
    return jsonify(response_data), 200

@bp.route('/paths/<path_name>/recording/settings', methods=['GET'])
@jwt_required
def get_recording_settings(path_name):
    """Get detailed recording settings for a specific path."""
    # Check if path exists in database
    stream_path = StreamPath.query.filter_by(path_name=path_name).first()
    if not stream_path:
        return jsonify({'message': 'Path not found'}), 404
    
    # Check if user owns the path
    if stream_path.owner != g.current_user:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        # Get path configuration from MediaMTX
        url = f"{get_mediamtx_api_url()}/config/paths/get/{path_name}"
        response = requests.get(url)
        response.raise_for_status()
        path_config = response.json()
        
        return jsonify({
            'path_name': path_name,
            'recording_enabled': path_config.get('record', False),
            'segment_duration': path_config.get('recordSegmentDuration', '1h'),
            'record_path': path_config.get('recordPath', ''),
            'record_format': path_config.get('recordFormat', 'fmp4')
        }), 200
    except requests.exceptions.RequestException as e:
        return jsonify({'message': 'Failed to get recording settings', 'error': str(e)}), 500