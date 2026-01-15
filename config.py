import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-tres-secrete-a-changer'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuration Uploads
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max

class DevelopmentConfig(Config):
    DEBUG = True
    # SQLite local pour le dev WSL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'dev_intranet_v2.db')

class ProductionConfig(Config):
    DEBUG = False
    # PostgreSQL pour la prod (Debian)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


    # --- CONFIGURATION EMAIL EXCHANGE ---
    # Adresse du serveur Exchange 
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or '192.168.1.4' 
    
    # Port : 25 (Standard interne) ou 587 (TLS)
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    
    # Sécurité : Mettre True si vous utilisez le port 587
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') is not None
    
    # Authentification 
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or 'intranet@ilvm.lan'
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or 'VotreMotDePasse'
    
    # L'adresse qui apparaîtra dans "Expéditeur"
    MAIL_DEFAULT_SENDER = 'intranet@ilvm.lan'
    
    # Pour le débogage 
    MAIL_DEBUG = False
