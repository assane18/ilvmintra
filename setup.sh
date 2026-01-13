#!/bin/bash

# Script d'installation TOTAL pour Debian 12
# À lancer depuis le dossier contenant les fichiers du projet sur le serveur
# Usage: sudo ./setup_production.sh

# --- VARIABLES ---
TARGET_DIR="/var/www/intranet"
DB_NAME="intranet_db"
DB_USER="intranet_user"
# Nouveau mot de passe sans '@' pour éviter les erreurs de parsing d'URL SQLAlchemy
DB_PASS="y89#nC$*Xt_Hur" 
DOMAIN_NAME="ilvmintra1" # Nom machine/Domaine
SERVER_IP="192.168.1.25"
LDAP_SERVER="192.168.1.9"

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Vérification Root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Erreur : Ce script doit être lancé avec sudo.${NC}"
  exit 1
fi

echo -e "${BLUE}=== 1. MISE À JOUR ET DÉPENDANCES ===${NC}"
apt-get update
apt-get install -y python3-pip python3-dev python3-venv build-essential \
    libldap2-dev libsasl2-dev libssl-dev \
    libpq-dev postgresql postgresql-contrib \
    nginx git curl dnsutils acl

echo -e "${BLUE}=== 2. PRÉPARATION DES FICHIERS ===${NC}"
# Création du dossier cible
mkdir -p $TARGET_DIR

# Copie des fichiers du dossier courant vers /var/www/intranet
echo "Copie des fichiers vers $TARGET_DIR..."
cp -r . $TARGET_DIR/

# Nettoyage des fichiers inutiles copiés (venv local, git, etc)
rm -rf $TARGET_DIR/venv
rm -rf $TARGET_DIR/.git
rm -rf $TARGET_DIR/__pycache__
rm -f $TARGET_DIR/dev_intranet_v2.db

# Permissions
echo "Configuration des permissions..."
# On donne la propriété à l'utilisateur courant (pour l'édition) et au groupe www-data
REAL_USER=$(logname)
chown -R $REAL_USER:www-data $TARGET_DIR
chmod -R 775 $TARGET_DIR

echo -e "${BLUE}=== 3. ENVIRONNEMENT PYTHON ===${NC}"
cd $TARGET_DIR

# Création venv
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# Installation dépendances
echo "Installation des librairies Python..."
# On s'assure que pip est à jour
pip install --upgrade pip
# Installation des paquets requis
pip install flask flask-sqlalchemy flask-login flask-migrate python-dotenv pandas openpyxl psycopg2-binary gunicorn ldap3

echo -e "${BLUE}=== 4. BASE DE DONNÉES POSTGRESQL ===${NC}"
# Configuration PostgreSQL
# On vérifie si l'utilisateur existe déjà pour éviter les erreurs
# Note: Si l'utilisateur existe déjà avec l'ancien mot de passe, on le met à jour
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
# Force la mise à jour du mot de passe pour être sûr qu'il correspond à celui du script
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

echo -e "${BLUE}=== 5. CONFIGURATION .ENV ===${NC}"
# Génération du fichier .env de production avec vos infos LDAP
cat > .env <<EOL
FLASK_APP=run.py
FLASK_DEBUG=0
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost/$DB_NAME
# Important pour que Flask sache qu'il est dans un sous-dossier /intranet
SCRIPT_NAME=/intranet

# Configuration LDAP ($DOMAIN_NAME)
LDAP_HOST=$LDAP_SERVER
LDAP_DOMAIN=ilvm.lan
LDAP_BASE_DN=DC=ilvm,DC=lan
# Compte de service AD (aintra)
LDAP_USER_DN='CN=Admin Intra,CN=Users,DC=ilvm,DC=lan'
LDAP_USER_PASSWORD='gq!nsXPYsM!LmFh4'
EOL

# Permissions sur le .env (sensible)
chmod 640 .env
chown $REAL_USER:www-data .env

echo -e "${BLUE}=== 6. INITIALISATION BDD (MIGRATIONS) ===${NC}"
# On tente d'initialiser la structure
export FLASK_APP=run.py
if [ -d "migrations" ]; then
    echo "Dossier migrations existant, on tente une mise à jour..."
    flask db upgrade
else
    echo "Initialisation complète de la BDD..."
    flask db init
    flask db migrate -m "Initial Deploy"
    flask db upgrade
fi

# Création d'un admin de secours si la table est vide
echo "Vérification Admin..."
python3 -c "
from app import create_app, db
from app.models import User, UserRole
app = create_app('production')
with app.app_context():
    try:
        if not User.query.filter_by(username='admin').first():
            u = User(username='admin', role=UserRole.ADMIN, fullname='Super Admin Local')
            db.session.add(u)
            db.session.commit()
            print('Admin local créé (user: admin).')
    except Exception as e:
        print(f'Erreur lors de la création de l\'admin: {e}')
"

echo -e "${BLUE}=== 7. CONFIGURATION SYSTEMD (GUNICORN) ===${NC}"
cat > /etc/systemd/system/intranet.service <<EOL
[Unit]
Description=Gunicorn instance to serve Intranet V2
After=network.target

[Service]
User=$REAL_USER
Group=www-data
WorkingDirectory=$TARGET_DIR
Environment="PATH=$TARGET_DIR/venv/bin"
EnvironmentFile=$TARGET_DIR/.env
# On ajoute SCRIPT_NAME pour le routage Flask
Environment="SCRIPT_NAME=/intranet"
ExecStart=$TARGET_DIR/venv/bin/gunicorn --workers 3 --bind unix:intranet.sock -m 007 run:app

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable intranet
systemctl restart intranet

echo -e "${BLUE}=== 8. CONFIGURATION NGINX ===${NC}"
cat > /etc/nginx/sites-available/intranet <<EOL
server {
    listen 80;
    server_name $DOMAIN_NAME $SERVER_IP ilvm.lan;

    # Accès via /intranet
    location /intranet {
        include proxy_params;
        proxy_pass http://unix:$TARGET_DIR/intranet.sock;
        
        # Réglages importants pour le sous-répertoire
        proxy_set_header X-Script-Name /intranet;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Host \$host;
        proxy_redirect off;
    }

    # Fichiers statiques (CSS, JS, Images)
    location /intranet/static {
        alias $TARGET_DIR/app/static;
    }
    
    # Redirection racine vers /intranet (Optionnel)
    location = / {
        return 301 /intranet;
    }
}
EOL

# Activation
ln -sf /etc/nginx/sites-available/intranet /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo -e "${GREEN}=== DÉPLOIEMENT TERMINÉ AVEC SUCCÈS ===${NC}"
echo "L'application est en ligne sur http://$DOMAIN_NAME/intranet (ou http://$SERVER_IP/intranet)"
echo "Les fichiers sont installés dans $TARGET_DIR"
