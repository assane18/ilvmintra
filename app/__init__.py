import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from config import config


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

    # Enregistrement OBLIGATOIRE des 3 Blueprints
    from .routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from .routes.main import main_bp
    app.register_blueprint(main_bp)
    
    from .routes.tickets import tickets_bp
    app.register_blueprint(tickets_bp, url_prefix='/tickets')

    # NOUVEAU : Module Inventaire
    from .routes.inventaire import inventaire_bp
    app.register_blueprint(inventaire_bp) # Pas de préfixe pour garder /inventaire direct

    from .routes.prets import prets_bp
    app.register_blueprint(prets_bp)

    # NOUVEAU : Module Users
    from .routes.users import users_bp
    app.register_blueprint(users_bp)

    from .routes.api import api_bp
    app.register_blueprint(api_bp)

    # NOUVEAU : Module FCPI
    from .routes.fcpi import fcpi_bp
    app.register_blueprint(fcpi_bp)

    return app
