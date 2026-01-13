#!/bin/bash

# Script de lancement automatique Intranet V2 (Mode Reset Total)
# Usage: ./launch.sh

echo "=== Démarrage Intranet V2 (Mode Reset) ==="

# 1. Vérifier/Créer l'environnement virtuel
if [ ! -d "venv" ]; then
    echo ">> Création de l'environnement virtuel..."
    python3 -m venv venv
fi

# 2. Activer l'environnement
source venv/bin/activate

# 3. Installer les dépendances (y compris pandas et openpyxl)
echo ">> Installation des librairies..."
pip install flask flask-sqlalchemy flask-login flask-migrate python-dotenv pandas openpyxl > /dev/null

# 4. Vérifier les dossiers critiques
if [ ! -f "app/templates/base.html" ]; then
    echo "ERREUR : Le fichier app/templates/base.html est manquant !"
    exit 1
fi

# 5. REINITIALISATION FORCEE DE LA BDD (Pour corriger l'erreur 'no such table')
echo ">> Nettoyage et Réinitialisation de la Base de Données..."
if [ -f "dev_intranet_v2.db" ]; then
    rm dev_intranet_v2.db
    echo "   - Ancienne base supprimée."
fi

if [ -d "migrations" ]; then
    rm -rf migrations
    echo "   - Anciennes migrations supprimées."
fi

export FLASK_APP=run.py
flask db init > /dev/null
flask db migrate -m "Reset Full Schema" > /dev/null
flask db upgrade > /dev/null
echo ">> Nouvelle base de données générée avec succès (Tables: users, tickets, materiels, prets...)."

# 6. Lancement du serveur
echo ">> Lancement du serveur..."
echo "Accédez à : http://localhost:5000"
echo "Utilisez l'utilisateur 'admin' (mdp: password) pour tester l'inventaire."
export FLASK_APP=run.py
export FLASK_DEBUG=1
flask run --host=0.0.0.0
