import os
import shutil
from app import create_app, db
from app.models import User, UserRole, ServiceType
from werkzeug.security import generate_password_hash

# Initialisation de l'application
app = create_app()

def clean_uploads():
    """Supprime tous les fichiers dans static/uploads"""
    upload_path = os.path.join(app.root_path, 'static', 'uploads')
    
    if os.path.exists(upload_path):
        print(f"🧹 Nettoyage du dossier : {upload_path}")
        try:
            # Supprime tout le dossier et son contenu
            shutil.rmtree(upload_path)
            # Le recrée vide
            os.makedirs(upload_path)
            print("✅ Dossier uploads vidé et recréé.")
        except Exception as e:
            print(f"❌ Erreur lors du nettoyage des fichiers : {e}")
    else:
        os.makedirs(upload_path)
        print("✅ Dossier uploads créé.")

def reset_database():
    """Supprime toutes les tables et les recrée"""
    print("💥 Suppression de toute la Base de Données...")
    db.drop_all() # Supprime TOUTES les tables (Users, Tickets, Messages, Tout)
    
    print("🏗️  Création de la nouvelle structure...")
    db.create_all() # Recrée les tables vides
    print("✅ Base de données remise à zéro.")

def create_admin():
    """Recrée le compte Admin par défaut pour ne pas être bloqué"""
    print("👤 Création du compte Administrateur par défaut...")
    
    # Adaptez ces infos selon vos besoins
    admin = User(
        email='admin@intranet.local',
        fullname='Administrateur Système',
        # MODIFICATION ICI : on utilise 'password' au lieu de 'password_hash'
        password=generate_password_hash('admin123'), 
        role=UserRole.ADMIN,
        service=ServiceType.INFO,
        is_active=True
    )
    
    db.session.add(admin)
    db.session.commit()
    print(f"✅ Admin créé : {admin.email} / admin123")
if __name__ == "__main__":
    with app.app_context():
        # 1. Nettoyer les fichiers
        clean_uploads()
        
        # 2. Vider la BDD
        reset_database()
        
        # 3. Créer un Admin (Obligatoire pour se reconnecter)
        create_admin()
        
        print("\n✨ RESET COMPLET TERMINÉ AVEC SUCCÈS ! ✨")
