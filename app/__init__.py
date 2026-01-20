import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from config import config
from werkzeug.middleware.proxy_fix import ProxyFix

# --- CORRECTIF POUR LES REDIRECTIONS (IMPORTANT) ---
class ForceHostFix:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # Nettoie les en-têtes dupliqués (ex: "ilvmintra1, ilvmintra1")
        headers_to_fix = ['HTTP_HOST', 'HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_SERVER']
        for key in headers_to_fix:
            if key in environ and ',' in environ[key]:
                environ[key] = environ[key].split(',')[0].strip()
        return self.app(environ, start_response)
# ---------------------------------------------------

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = 'dev-key-fixe-pour-test'

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)

    # Enregistrement des Blueprints
    from .routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .routes.main import main_bp
    app.register_blueprint(main_bp)

    from .routes.tickets import tickets_bp
    app.register_blueprint(tickets_bp, url_prefix='/tickets')

    from .routes.inventaire import inventaire_bp
    app.register_blueprint(inventaire_bp) 

    from .routes.prets import prets_bp
    app.register_blueprint(prets_bp)

    from .routes.users import users_bp
    app.register_blueprint(users_bp)

    from .routes.api import api_bp
    app.register_blueprint(api_bp)

    from .routes.fcpi import fcpi_bp
    app.register_blueprint(fcpi_bp)

    # Application des correctifs Proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.wsgi_app = ForceHostFix(app.wsgi_app) # Indispensable pour votre serveur

    return app
