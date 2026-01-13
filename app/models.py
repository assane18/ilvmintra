from . import db
from flask_login import UserMixin
from datetime import datetime
import enum
import json

# --- ÉNUMÉRATIONS ---

class UserRole(str, enum.Enum):
    USER = "USER"
    MANAGER = "MANAGER"     # N+1
    DIRECTEUR = "DIRECTEUR" # N+2
    SOLVER = "SOLVER"       # Technicien qui traite
    ADMIN = "ADMIN"

class TicketStatus(str, enum.Enum):
    VALIDATION_N1 = "VALIDATION_HIERARCHIQUE"  # Validation Manager/Directeur du demandeur
    VALIDATION_N2 = "VALIDATION_TECHNIQUE"     # Validation par le service destinataire (Budget/Faisabilité)
    PENDING = "EN_ATTENTE_TRAITEMENT"          # Validé, en attente d'attribution (Pool)
    IN_PROGRESS = "EN_COURS"
    WAITING_USER = "EN_ATTENTE_USER"
    REFUSED = "REFUSE"
    DONE = "TERMINE"

class ServiceType(str, enum.Enum):
    # Liste des services destinataires (GS)
    INFO = "INFORMATIQUE"
    DAF = "DAF"
    GEN = "GENERAUX"
    TECH = "TECHNIQUE"
    DRH = "DRH"
    SECU = "SECU"
    # Fallback pour l'affichage
    AUTRE = "AUTRE"

# --- MODÈLES ---

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    fullname = db.Column(db.String(120))
    email = db.Column(db.String(120))
    
    role = db.Column(db.Enum(UserRole), default=UserRole.USER)
    
    # Stockage JSON des groupes AD
    # origin_services (GU) : D'où vient l'utilisateur (ex: ["GU-DAF", "GU-MAS"])
    origin_services_json = db.Column(db.Text, default='[]')
    
    # allowed_services (GS) : Ce que l'utilisateur peut traiter (ex: ["GS-INFORMATIQUE"])
    allowed_services_json = db.Column(db.Text, default='[]')

    location = db.Column(db.String(100), nullable=True) # Lieu physique

    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_origin_services(self, services_list):
        self.origin_services_json = json.dumps(services_list)

    def get_origin_services(self):
        try: return json.loads(self.origin_services_json)
        except: return []

    def set_allowed_services(self, services_list):
        self.allowed_services_json = json.dumps(services_list)

    def get_allowed_services(self):
        try: return json.loads(self.allowed_services_json)
        except: return []

    def __repr__(self):
        return f'<User {self.username}>'

class Ticket(db.Model):
    __tablename__ = 'tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    uid_public = db.Column(db.String(20), unique=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User', foreign_keys=[author_id], backref='my_tickets')
    
    target_service = db.Column(db.Enum(ServiceType), nullable=False) # Le service qui reçoit (GS)
    status = db.Column(db.Enum(TicketStatus), default=TicketStatus.VALIDATION_N1)
    
    solver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    solver = db.relationship('User', foreign_keys=[solver_id], backref='assigned_tickets')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    category_ticket = db.Column(db.String(50)) 
    hostname = db.Column(db.String(64), nullable=True)
    
    # Service demandeur (Choisi parmi les GU de l'user)
    service_demandeur = db.Column(db.String(100), nullable=True)
    
    tel_demandeur = db.Column(db.String(20), nullable=True)
    lieu_installation = db.Column(db.String(100), nullable=True)

    # Champs spécifiques (Nouvel user, Matériel, DAF...)
    new_user_fullname = db.Column(db.String(150), nullable=True)
    new_user_service = db.Column(db.String(100), nullable=True)
    new_user_acces = db.Column(db.String(255), nullable=True)
    new_user_date = db.Column(db.DateTime, nullable=True)
    
    materiel_list = db.Column(db.Text, nullable=True)
    destinataire_materiel = db.Column(db.String(150), nullable=True)
    service_destinataire = db.Column(db.String(100), nullable=True)

    daf_lieu_livraison = db.Column(db.String(100))
    daf_fournisseur_nom = db.Column(db.String(100))
    daf_fournisseur_tel = db.Column(db.String(50))
    daf_fournisseur_fax = db.Column(db.String(50))
    daf_fournisseur_email = db.Column(db.String(100))
    daf_type_prix = db.Column(db.String(10))
    
    daf_lignes_json = db.Column(db.Text) 
    daf_files_json = db.Column(db.Text)

    def get_daf_lignes(self):
        if self.daf_lignes_json:
            try: return json.loads(self.daf_lignes_json)
            except: return []
        return []

    def get_daf_files(self):
        if self.daf_files_json:
            try: return json.loads(self.daf_files_json)
            except: return []
        return []

class TicketMessage(db.Model):
    __tablename__ = 'ticket_messages'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'))
    ticket = db.relationship('Ticket', backref='messages')
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User')

class TeamMessage(db.Model):
    __tablename__ = 'team_messages'
    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.Enum(ServiceType), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User')

# --- MODÈLES INVENTAIRE & PRETS (Inchangés) ---
class Materiel(db.Model):
    __tablename__ = 'materiels'
    id = db.Column(db.Integer, primary_key=True)
    categorie = db.Column(db.String(50))
    modele = db.Column(db.String(100))
    sn = db.Column(db.String(100), unique=True)
    hostname = db.Column(db.String(100))
    imei = db.Column(db.String(100))
    statut = db.Column(db.String(50), default='Disponible')

class Pret(db.Model):
    __tablename__ = 'prets'
    id = db.Column(db.Integer, primary_key=True)
    materiel_id = db.Column(db.Integer, db.ForeignKey('materiels.id'))
    materiel = db.relationship('Materiel', backref='historique_prets')
    technicien_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    technicien = db.relationship('User', backref='prets_geres')
    nom_emprunteur = db.Column(db.String(100))
    prenom_emprunteur = db.Column(db.String(100))
    service_emprunteur = db.Column(db.String(100))
    date_sortie = db.Column(db.DateTime, default=datetime.utcnow)
    date_retour_prevue = db.Column(db.DateTime, nullable=True)
    date_retour_reelle = db.Column(db.DateTime, nullable=True)
    statut_dossier = db.Column(db.String(20), default='En cours')
    type_pret = db.Column(db.String(50))
    accessoires = db.Column(db.String(255))
    etat_ecran_sortie = db.Column(db.String(50))
    etat_clavier_sortie = db.Column(db.String(50))
    etat_coque_sortie = db.Column(db.String(50))
    etat_ecran_retour = db.Column(db.String(50))
    etat_clavier_retour = db.Column(db.String(50))
    etat_coque_retour = db.Column(db.String(50))

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(20), default='info')
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
