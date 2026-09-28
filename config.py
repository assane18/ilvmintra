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

    # Connexion SSO Microsoft Entra ID (bouton "Intranet" de l'extranet SharePoint).
    # Inscription d'application dédiée "Intranet ILVM - Connexion SSO" ; les trois
    # valeurs viennent du .env. Si l'une manque, la route /auth/microsoft se
    # contente de renvoyer vers le formulaire LDAP classique.
    AZURE_SSO_TENANT_ID = os.environ.get('AZURE_SSO_TENANT_ID')
    AZURE_SSO_CLIENT_ID = os.environ.get('AZURE_SSO_CLIENT_ID')
    AZURE_SSO_CLIENT_SECRET = os.environ.get('AZURE_SSO_CLIENT_SECRET')

    # Annuaire AD : serveur/base pour le bind utilisateur du formulaire de login,
    # + compte de service (déjà utilisé par app/tech/routes.py) pour la recherche
    # par UPN de la connexion SSO. Valeurs du .env, défauts historiques sinon.
    LDAP_SERVER = 'ldap://' + os.environ.get('LDAP_HOST', '192.168.1.9')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN', 'dc=ilvm,dc=lan')
    LDAP_USER_DN = os.environ.get('LDAP_USER_DN')
    LDAP_USER_PASSWORD = os.environ.get('LDAP_USER_PASSWORD')

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
