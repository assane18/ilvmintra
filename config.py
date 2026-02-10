import os
import os
from dotenv import load_dotenv
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-tres-secrete-a-changer'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BASE_URL = 'https://ilvmintra1/intranet/'
    # Configuration Uploads
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB max

# Configuration Email Exchange Local
    MAIL_SERVER = 'ILVMExchangeSrv.Ilvm.lan'  # Ton serveur
    MAIL_PORT = 25                            # Port 25 (interne)
    MAIL_USE_TLS = False                      # Pas de TLS en interne sur port 25
    MAIL_USERNAME = None                      # Pas d'auth
    MAIL_PASSWORD = None                      # Pas d'auth
    # L'adresse qui s'affichera en expéditeur
    MAIL_DEFAULT_SENDER = 'no-reply-intranet@ilvm.lan' 
    MAIL_DEBUG = False

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
