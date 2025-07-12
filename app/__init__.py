import os
import click
from flask import Flask
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MEDIAMTX_API_URL=os.getenv('MEDIAMTX_API_URL'),
        MEDIAMTX_RECORDINGS_PATH=os.getenv('MEDIAMTX_RECORDINGS_PATH', './recordings')
    )

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    # Import models to ensure they are registered with SQLAlchemy
    from app import models

    # Register blueprints
    from app import routes
    app.register_blueprint(routes.bp)

    # Add custom CLI command
    app.cli.add_command(create_user_command)
    
    return app

@click.command('create-user')
@click.argument('username')
@click.argument('password')
@with_appcontext
def create_user_command(username, password):
    """Creates a new user."""
    from app.models import User
    
    if User.query.filter_by(username=username).first():
        click.echo(f"User '{username}' already exists.")
        return

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    click.echo(f"User '{username}' created successfully.")