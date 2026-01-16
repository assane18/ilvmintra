from . import db
from flask_login import UserMixin
from datetime import datetime
import enum
import json

class UserRole(str, enum.Enum):
    USER = "USER"
    MANAGER = "MANAGER"
    DIRECTEUR = "DIRECTEUR"
    SOLVER = "SOLVER"
    ADMIN = "ADMIN"

class TicketStatus(str, enum.Enum):
    VALIDATION_N1 = "VALIDATION_HIERARCHIQUE"
    VALIDATION_N2 = "VALIDATION_TECHNIQUE"
    DAF_SIGNATURE = "SIGNATURE_DIRECTEUR"
    PENDING = "EN_ATTENTE_TRAITEMENT"
    IN_PROGRESS = "EN_COURS"
    WAITING_USER = "EN_ATTENTE_USER"
    REFUSED = "REFUSE"
    DONE = "TERMINE"

class ServiceType(str, enum.Enum):
    INFO = "INFORMATIQUE"
    DAF = "DAF"
    GEN = "GENERAUX"
    TECH = "TECHNIQUE"
    DRH = "DRH"
    SECU = "SECU"
    AUTRE = "AUTRE"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    fullname = db.Column(db.String(120))
    email = db.Column(db.String(120))
    role = db.Column(db.Enum(UserRole), default=UserRole.USER)
    origin_services_json = db.Column(db.Text, default='[]')
    allowed_services_json = db.Column(db.Text, default='[]')
    location = db.Column(db.String(100), nullable=True)
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_origin_services(self, services_list):
        try: self.origin_services_json = json.dumps(services_list)
        except: self.origin_services_json = '[]'

    def get_origin_services(self):
        try: return json.loads(self.origin_services_json) or []
        except: return []

    def set_allowed_services(self, services_list):
        try: self.allowed_services_json = json.dumps(services_list)
        except: self.allowed_services_json = '[]'

    def get_allowed_services(self):
        try: return json.loads(self.allowed_services_json) or []
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
    target_service = db.Column(db.Enum(ServiceType), nullable=False)
    status = db.Column(db.Enum(TicketStatus), default=TicketStatus.VALIDATION_N1)
    solver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    solver = db.relationship('User', foreign_keys=[solver_id], backref='assigned_tickets')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    category_ticket = db.Column(db.String(50)) 
    hostname = db.Column(db.String(64), nullable=True)
    service_demandeur = db.Column(db.String(100), nullable=True)
    tel_demandeur = db.Column(db.String(20), nullable=True)
    lieu_installation = db.Column(db.String(100), nullable=True)
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
    daf_uf = db.Column(db.String(50), nullable=True)
    daf_budget_affecte = db.Column(db.String(100), nullable=True)
    daf_new_supplier = db.Column(db.Boolean, default=False)
    daf_siret = db.Column(db.String(50), nullable=True)
    daf_fournisseur_tel_comment = db.Column(db.String(100), nullable=True)
    daf_rib_file = db.Column(db.String(255), nullable=True)
    daf_solver_file = db.Column(db.String(255), nullable=True)
    daf_signed_file = db.Column(db.String(255), nullable=True)

    def get_safe_status(self):
        if self.status is None: return "INCONNU"
        if hasattr(self.status, 'value'): return str(self.status.value)
        return str(self.status)

    def get_safe_target_service(self):
        if self.target_service is None: return "AUTRE"
        if hasattr(self.target_service, 'value'): return str(self.target_service.value)
        return str(self.target_service)

    def get_daf_lignes(self):
        if not self.daf_lignes_json: return []
        try: return json.loads(self.daf_lignes_json)
        except: return []

    def get_daf_files(self):
        if not self.daf_files_json: return []
        try: return json.loads(self.daf_files_json)
        except: return []

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

class Materiel(db.Model):
    __tablename__ = 'materiels'
    id = db.Column(db.Integer, primary_key=True)
    categorie = db.Column(db.String(50))
    modele = db.Column(db.String(100))
    sn = db.Column(db.String(100), unique=True)
    hostname = db.Column(db.String(100))
    imei = db.Column(db.String(100))
    statut = db.Column(db.String(50), default='Disponible')
    historique_prets = db.relationship('Pret', backref='materiel_rel', lazy='dynamic')

class Pret(db.Model):
    __tablename__ = 'prets'
    id = db.Column(db.Integer, primary_key=True)
    materiel_id = db.Column(db.Integer, db.ForeignKey('materiels.id'))
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
