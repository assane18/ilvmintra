import os
from flask import Flask
from app import create_app, db
from sqlalchemy import text

# Création de l'application context pour accéder à la DB
app = create_app(os.getenv('FLASK_CONFIG') or 'default')

with app.app_context():
    print("--- Tentative de mise à jour de l'ENUM 'servicetype' dans PostgreSQL ---")
    try:
        # On utilise une connection directe au moteur DB
        with db.engine.connect() as connection:
            # On passe en mode AUTOCOMMIT car ALTER TYPE ne peut pas toujours courir dans une transaction
            connection.execution_options(isolation_level="AUTOCOMMIT")
            
            print("Exécution: ALTER TYPE servicetype ADD VALUE 'IMAGO' ...")
            # Cette commande dit à PostgreSQL d'accepter 'IMAGO' comme valeur valide
            connection.execute(text("ALTER TYPE servicetype ADD VALUE 'IMAGO'"))
            
            print("✅ SUCCÈS : La valeur 'IMAGO' a été ajoutée à la base de données.")
            print("Vous pouvez maintenant créer des tickets Imago.")
            
    except Exception as e:
        # Si l'erreur contient "already exists", c'est que c'est déjà fait
        if "already exists" in str(e) or "déjà" in str(e):
            print("⚠️ INFO : La valeur 'IMAGO' semble déjà exister dans l'ENUM. Pas d'action nécessaire.")
        else:
            print(f"❌ ERREUR : {e}")
            print("\nSi le script échoue, connectez-vous à votre base de données (psql) et lancez manuellement :")
            print("ALTER TYPE servicetype ADD VALUE 'IMAGO';")
