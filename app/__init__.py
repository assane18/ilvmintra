import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail  # <--- AJOUT 1
from config import config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()  # <--- AJOUT 2

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Veuillez vous connecter.'

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    upload_path = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)  # <--- AJOUT 3

    # --- BLUEPRINTS ---
    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.tickets import tickets_bp
    from .routes.users import users_bp
    from .routes.inventaire import inventaire_bp
    from .routes.prets import prets_bp
    from .routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(inventaire_bp)
    app.register_blueprint(prets_bp)
    app.register_blueprint(api_bp)

    return app
