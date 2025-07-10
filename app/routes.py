import datetime
from flask import Blueprint, request, jsonify, g, current_app
import jwt
from app import db
from app.models import User, StreamPath
from app.decorators import jwt_required
from app.services import (
    add_path_to_mediamtx,
    get_mediamtx_connections,
    get_mediamtx_recordings
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