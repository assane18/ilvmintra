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
    
    # Configuration Uploads
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB max

    MAIL_SERVER = os.environ.get('MAIL_SERVER') or '192.168.1.4'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'no-reply-intranet@ilvm.lan'
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
