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
    VALIDATION_DAF_MANAGER = "VALIDATION_DAF_MANAGER"
    DAF_SIGNATURE = "SIGNATURE_DIRECTEUR"
    PENDING = "EN_ATTENTE_TRAITEMENT"
    IN_PROGRESS = "EN_COURS"
    WAITING_USER = "EN_ATTENTE_USER"
    REFUSED = "REFUSE"
    DONE = "TERMINE"

class ServiceType(str, enum.Enum):
    # Services Supports
    INFO = "INFORMATIQUE"
    DAF = "DAF"
    GEN = "GENERAUX"
    TECH = "TECHNIQUE"
    DRH = "DRH"
    SECU = "SECU"
    AUTRE = "AUTRE"
    IMAGO = "IMAGO"
    COMMUNICATION = "COMMUNICATION"
    MEDIATEAM = "MEDIATEAM"
    DRH_PAIE_CARRIERE = "DRH-PAIE_CARRIERE"
    DRH_RECRUTEMENT_FORMATION = "DRH-RECRUTEMENT_FORMATION"
    DRH_EFFECTIFS_SOCIAL = "DRH-EFFECTIFS_SOCIAL"

    # Tous les Services Établissements
    ACCUEIL = "Accueil"
    ARCHIPELLE = "Archipelle"
    CELLULE_PARCOURS = "Cellule Parcours"
    CSD = "CSD"
    DG = "DG"
    EAM_DRAVEIL = "EAM Draveil"
    ESAT = "ESAT"
    ESPACE_LOISIRS = "Espace Loisirs"
    FH = "FH"
    FJ = "FJ"
    FV = "FV"
    GITE = "Gite"
    IME_CORBEIL = "IME Corbeil"
    MAGASIN = "Magasin"
    MAS = "MAS"
    MAS_EXTERNAT = "MAS Externat"
    MAS_INCLUSIVE = "MAS Inclusive"
    PATRIMOINE = "Patrimoine"
    QUALITE = "Qualite"
    SACAT = "SACAT"
    SAMSAH = "SAMSAH"
    SAVIE = "SAVIE"
    SECURITE_INCENDIE = "Sécurité Incendie"
    SESSAD_CORBEIL = "SESSAD Corbeil"
    SESSAD_CRETEIL = "SESSAD Créteil"
    SESSAD_TSA = "SESSAD TSA"
    SG = "SG"
    SRU = "SRU"
    SYNDICAT = "Syndicat"
    TKITOI = "TKITOI"
    UEEA = "UEEA"
    UEMA = "UEMA"

class RecruitmentStatus(str, enum.Enum):
    WAITING_RH_MGR = "VALIDATION_RH_MANAGER"
    WAITING_RH_DIR = "VALIDATION_RH_DIRECTEUR"
    REFUSED = "REFUSE"
    DISPATCHED = "DISPATCHE_AUX_SERVICES"
    DONE = "TERMINE"

class SejourStatus(str, enum.Enum):
    VALIDATION_MANAGER = "VALIDATION_MANAGER"
    DISPATCHED = "DISPATCHE_AUX_SERVICES"
    REFUSED = "REFUSE"
    DONE = "TERMINE"

class PublicationStatus(str, enum.Enum):
    VALIDATION_DIRECTEUR = "VALIDATION_DIRECTEUR"
    EN_CORRECTION = "EN_CORRECTION"
    PUBLIE = "PUBLIE"
    REFUSE = "REFUSE"

class FormFieldType(str, enum.Enum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    DATE = "DATE"
    SELECT = "SELECT"
    MULTI_SELECT = "MULTI_SELECT"
    CHECKBOX = "CHECKBOX"
    NUMBER = "NUMBER"
    FILE = "FILE"
    MULTI_FILE = "MULTI_FILE"

class FormSubmissionStatus(str, enum.Enum):
    IN_PROGRESS = "EN_COURS"
    REFUSED = "REFUSE"
    DONE = "TERMINE"

class ServiceSource(str, enum.Enum):
    FIXED = "FIXED"
    EMITTER = "EMITTER"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    fullname = db.Column(db.String(120))
    email = db.Column(db.String(120))
    role = db.Column(db.Enum(UserRole), default=UserRole.USER)
    
    # Stockage JSON
    origin_services_json = db.Column(db.Text, default='[]')
    allowed_services_json = db.Column(db.Text, default='[]')
    
    location = db.Column(db.String(100), nullable=True)
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    # Profil personnalisable (panneau profil : photo/initiales/couleur d'accent)
    avatar_photo = db.Column(db.String(255), nullable=True)
    avatar_initials = db.Column(db.String(2), nullable=True)
    theme_color = db.Column(db.String(20), default='teal')

    # Coordonnées saisies par l'utilisateur lui-même (page /profile, onglet
    # "Mon compte") — le reste du compte est piloté par l'annuaire LDAP.
    phone = db.Column(db.String(30), nullable=True)
    office = db.Column(db.String(100), nullable=True)

    # Préférences d'apparence (page /profile, onglet "Apparence"), appliquées
    # via des attributs data-* sur <html> dans base.html. Stockées en base (et
    # non en localStorage) pour suivre l'utilisateur d'un poste à l'autre.
    theme_mode = db.Column(db.String(10), default='auto')       # light | dark | auto
    font_scale = db.Column(db.String(10), default='normal')     # normal | large | xlarge
    density = db.Column(db.String(12), default='comfortable')   # comfortable | compact
    high_contrast = db.Column(db.Boolean, default=False)

    # Préférence e-mail (page /profile) : all = chaque événement (défaut),
    # important = clôture / validation / affectation mais pas chaque message du
    # chat, daily = un seul résumé par jour (scripts/resume_quotidien.py).
    # Filtrée centralement dans app/emails.py::send_email.
    email_mode = db.Column(db.String(10), default='all')

    @property
    def service(self):
        origins = self.get_origin_services()
        return origins[0] if origins else "AUCUN"

    @property
    def display_initials(self):
        if self.avatar_initials:
            return self.avatar_initials.upper()
        return (self.fullname or '?')[:2].upper()

    def set_origin_services(self, services_list):
        try: self.origin_services_json = json.dumps(services_list)
        except: self.origin_services_json = '[]'

    def get_origin_services(self):
        if not self.origin_services_json: return []
        try: return json.loads(self.origin_services_json) or []
        except: return []

    def set_allowed_services(self, services_list):
        try: self.allowed_services_json = json.dumps(services_list)
        except: self.allowed_services_json = '[]'

    def get_allowed_services(self):
        if not self.allowed_services_json: return []
        try: return json.loads(self.allowed_services_json) or []
        except: return []

    def __repr__(self):
        return f'<User {self.username}>'

class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.Integer, primary_key=True)
    uid_public = db.Column(db.String(30), unique=True, index=True)
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

    # Boucle qualité (2026-09-28) : avis du demandeur à la clôture (1 insatisfait,
    # 2 neutre, 3 satisfait) et nombre de réouvertures "ce n'est pas résolu".
    satisfaction = db.Column(db.SmallInteger, nullable=True)
    satisfaction_comment = db.Column(db.Text, nullable=True)
    satisfaction_at = db.Column(db.DateTime, nullable=True)
    reopen_count = db.Column(db.Integer, default=0)

    # Traçabilité de la dernière validation manager (temps moyen de validation
    # sur le tableau de bord manager) — renseigné par tickets._validate_ticket.
    validated_at = db.Column(db.DateTime, nullable=True)
    validated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Horodatage de la PREMIÈRE prise en charge (passage à IN_PROGRESS) — nul
    # pour les tickets historiques créés avant l'ajout de cette colonne, à
    # exclure du calcul des délais d'assignation plutôt que compté comme 0.
    assigned_at = db.Column(db.DateTime, nullable=True)
    category_ticket = db.Column(db.String(50))
    hostname = db.Column(db.String(64), nullable=True)
    service_demandeur = db.Column(db.String(100), nullable=True)
    tel_demandeur = db.Column(db.String(20), nullable=True)
    lieu_installation = db.Column(db.String(100), nullable=True)
    
    # Champs DRH/FCPI
    rdv_date = db.Column(db.DateTime, nullable=True)
    new_user_fullname = db.Column(db.String(150), nullable=True)
    new_user_service = db.Column(db.String(100), nullable=True)
    new_user_acces = db.Column(db.String(255), nullable=True)
    new_user_date = db.Column(db.DateTime, nullable=True)
    materiel_list = db.Column(db.Text, nullable=True)
    destinataire_materiel = db.Column(db.String(150), nullable=True)
    service_destinataire = db.Column(db.String(100), nullable=True)
    
    # Champs DAF
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

    # --- Lot 6 : tickets liés / fusion de doublons ---
    # Un ticket « doublon » pointe vers son ticket maître ; le maître expose
    # ses doublons via `duplicates`. Un doublon ne peut pas être lui-même
    # maître (règle appliquée dans app/routes/tech_extras.py::link_duplicate).
    parent_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=True)
    parent = db.relationship('Ticket', remote_side=[id], foreign_keys=[parent_id],
                             backref=db.backref('duplicates', lazy='select'))

    @property
    def is_duplicate(self):
        return self.parent_id is not None

    def open_duplicates(self):
        """Doublons rattachés encore ouverts (ni terminés ni refusés)."""
        return [d for d in (self.duplicates or [])
                if d.status not in (TicketStatus.DONE, TicketStatus.REFUSED)]
    # --- fin Lot 6 ---

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
        try: return json.loads(self.daf_lignes_json) or []
        except: return []

    def get_daf_files(self):
        if not self.daf_files_json: return []
        try: return json.loads(self.daf_files_json) or []
        except: return []

    @property
    def author_name(self):
        """Retourne le nom de l'auteur ou 'Inconnu' si supprimé."""
        return self.author.username if self.author else "Utilisateur supprimé"

    @property
    def age_hours(self):
        """Âge du ticket en heures depuis sa création (horloge serveur,
        Europe/Paris — cohérent avec get_paris_time() côté création)."""
        if not self.created_at:
            return 0
        return (datetime.now() - self.created_at).total_seconds() / 3600

    @property
    def sla_hours(self):
        """Délai cible (h) selon service + catégorie — voir app/sla.py."""
        from app.sla import sla_hours_for
        return sla_hours_for(self.target_service, self.category_ticket)

    @property
    def sla_remaining_hours(self):
        return self.sla_hours - self.age_hours

    @property
    def due_at(self):
        from datetime import timedelta
        return self.created_at + timedelta(hours=self.sla_hours) if self.created_at else None

    @property
    def sla_label(self):
        """« échéance dans 3 h » / « dépassé de 2 j » (cartes de l'Espace Tech)."""
        from app.sla import format_remaining
        return format_remaining(self.sla_remaining_hours)

    @property
    def is_stale(self):
        """Ticket réellement 'en retard' : encore à traiter par un
        technicien (PENDING/IN_PROGRESS — pas en attente de validation N1/N2,
        qui dépend d'un manager, pas d'un solver) et dont le délai cible
        (SLA par service/catégorie, 24h par défaut) est dépassé."""
        return self.status in (TicketStatus.PENDING, TicketStatus.IN_PROGRESS) and self.age_hours > self.sla_hours

    def __repr__(self):
        # IMPORTANT: Ne pas inclure de relations (author, solver) ici pour éviter la récursion
        return f'<Ticket {self.uid_public}>'

class Recruitment(db.Model):
    __tablename__ = 'recruitments'
    id = db.Column(db.Integer, primary_key=True)
    uid_public = db.Column(db.String(20), unique=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User', backref='my_recruitments')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.Enum(RecruitmentStatus), default=RecruitmentStatus.WAITING_RH_MGR)
    date_entree = db.Column(db.DateTime)
    nom_agent = db.Column(db.String(100))
    prenom_agent = db.Column(db.String(100))
    fonction = db.Column(db.String(100))
    service_agent = db.Column(db.String(100))
    uf_agent = db.Column(db.String(50))
    contractuel = db.Column(db.Boolean, default=False)
    date_debut_contrat = db.Column(db.DateTime, nullable=True)
    date_fin_contrat = db.Column(db.DateTime, nullable=True)
    condition_recrutement = db.Column(db.String(50)) 
    temps_travail = db.Column(db.String(50)) 
    pourcentage_temps = db.Column(db.String(20), nullable=True)
    motif_recrutement = db.Column(db.String(50)) 
    simulation_salaire = db.Column(db.Boolean, default=False)
    localisation_poste = db.Column(db.String(100))
    commentaire_securite = db.Column(db.Text)
    imago_active = db.Column(db.Boolean, default=False)
    imago_mobilite = db.Column(db.String(200), nullable=True)
    materiels_demandes = db.Column(db.String(255))
    acces_informatique = db.Column(db.Text)
    file_cv = db.Column(db.String(255))
    file_fiche_poste = db.Column(db.String(255))
    file_photo = db.Column(db.String(255))
    refusal_reason = db.Column(db.Text)
    child_tickets_ids = db.Column(db.Text, default='[]') 

    def get_child_tickets(self):
        if not self.child_tickets_ids: return []
        try: return json.loads(self.child_tickets_ids) or []
        except: return []

    def get_child_tickets_objects(self):
        ids = self.get_child_tickets()
        if not ids: return []
        # Utilisation de in_ avec une liste vide peut causer des erreurs SQL sur certaines DB, d'où la vérif ci-dessus
        return Ticket.query.filter(Ticket.id.in_(ids)).all()

    @property
    def is_fully_completed(self):
        tickets = self.get_child_tickets_objects()
        if not tickets: return False
        return all(t.status == TicketStatus.DONE for t in tickets)

    @property
    def author_name(self):
        """Retourne le nom de l'auteur ou 'Inconnu' si supprimé."""
        return self.author.username if self.author else "Utilisateur supprimé"

    def __repr__(self):
        # IMPORTANT: Ne pas inclure de relations ici
        return f'<Recruitment {self.uid_public}>'

class Announcement(db.Model):
    """Annonce affichée en bandeau sur le portail entre starts_at et ends_at.
    Publiable par les ADMIN et le service Communication (/announcements/manage)."""
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(10), default='info')  # info | warning | urgent
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User')

    def is_visible(self, now=None):
        now = now or datetime.utcnow()
        if self.is_active is False: return False  # None = pas encore flushé, défaut actif
        if self.starts_at and now < self.starts_at: return False
        if self.ends_at and now > self.ends_at: return False
        return True

class SlaRule(db.Model):
    """Délai cible (heures) par service, éventuellement affiné par catégorie de
    ticket (category=None = toutes les catégories du service). /admin/sla."""
    __tablename__ = 'sla_rules'
    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(60), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=True)
    hours = db.Column(db.Integer, nullable=False, default=24)
    is_active = db.Column(db.Boolean, default=True)

class HelpTip(db.Model):
    """Conseil affiché AVANT l'envoi d'une demande ("Avez-vous essayé…"),
    ciblé par contexte : slug d'un formulaire du moteur (ex: 'info-v2') ou nom
    de service d'une route legacy (ex: 'DAF'). Géré dans /admin/help-contents."""
    __tablename__ = 'help_tips'
    id = db.Column(db.Integer, primary_key=True)
    context = db.Column(db.String(60), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

class CannedResponse(db.Model):
    """Réponse type proposée aux techniciens dans le chat d'un ticket.
    service=None => proposée sur tous les services."""
    __tablename__ = 'canned_responses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    body = db.Column(db.Text, nullable=False)
    service = db.Column(db.String(60), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

class TicketMessage(db.Model):
    __tablename__ = 'ticket_messages'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'))
    ticket = db.relationship('Ticket', backref='messages')
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User')

    # --- Lot 6 : notes internes et pièces jointes du chat ---
    # is_internal : note visible uniquement par l'équipe (jamais rendue au
    # demandeur, ni dans la page ni dans les e-mails/notifications).
    is_internal = db.Column(db.Boolean, default=False)
    # attachments_json : liste JSON des noms de fichiers enregistrés dans
    # uploads/tickets/<uid_public>/ (préfixe msg_<id>_).
    attachments_json = db.Column(db.Text, nullable=True)

    def get_attachments(self):
        if not self.attachments_json: return []
        try: return json.loads(self.attachments_json) or []
        except: return []
    # --- fin Lot 6 ---

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
    historique_prets = db.relationship('Pret', backref='materiel', lazy='dynamic')

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


class DossierSejour(db.Model):
    __tablename__ = 'dossiers_sejour'
    id = db.Column(db.Integer, primary_key=True)
    uid_public = db.Column(db.String(30), unique=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User', backref='my_sejours')
    status = db.Column(db.Enum(SejourStatus), default=SejourStatus.VALIDATION_MANAGER)
    titre = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_sejour = db.Column(db.DateTime, nullable=True)
    service_demandeur = db.Column(db.String(100), nullable=True)
    file_dossier = db.Column(db.String(255), nullable=True)
    file_dossier_signe = db.Column(db.String(255), nullable=True)
    file_pv_securite = db.Column(db.String(255), nullable=True)
    file_devis = db.Column(db.String(255), nullable=True)
    refusal_reason = db.Column(db.Text, nullable=True)
    child_tickets_ids = db.Column(db.Text, default='[]')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_child_tickets(self):
        if not self.child_tickets_ids: return []
        try: return json.loads(self.child_tickets_ids) or []
        except: return []

    @property
    def author_name(self):
        return self.author.username if self.author else "Utilisateur supprimé"

    def __repr__(self):
        return f'<DossierSejour {self.uid_public}>'


class Publication(db.Model):
    __tablename__ = 'publications'
    id = db.Column(db.Integer, primary_key=True)
    uid_public = db.Column(db.String(30), unique=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User', backref='my_publications')
    status = db.Column(db.Enum(PublicationStatus), default=PublicationStatus.VALIDATION_DIRECTEUR)
    titre = db.Column(db.String(200), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    files_json = db.Column(db.Text, default='[]')
    refusal_reason = db.Column(db.Text, nullable=True)
    communication_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_files(self):
        if not self.files_json: return []
        try: return json.loads(self.files_json) or []
        except: return []

    @property
    def author_name(self):
        return self.author.username if self.author else "Utilisateur supprimé"

    def __repr__(self):
        return f'<Publication {self.uid_public}>'


class FormDefinition(db.Model):
    __tablename__ = 'form_definitions'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, index=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Réservé aux Manager/Directeur/Admin pour la SOUMISSION (pas la validation),
    # comme "Demande Matériel" ou FCPI aujourd'hui. Appliqué côté route
    # (new_submission) — le lien reste visible sur le portail avec un badge,
    # même pattern "piège" que l'existant.
    manager_only = db.Column(db.Boolean, default=False)

    # Colonnes structurées de Ticket calculées à partir de PLUSIEURS champs
    # combinés (ex: new_user_fullname = "$nom_agent $prenom_agent"), pour les
    # cas que le mapping 1:1 de FormField.maps_to_ticket_field ne peut pas
    # exprimer. JSON : {colonne_ticket: "template $champ"}. Appliqué à TOUS
    # les tickets créés par la soumission (comme service_demandeur/
    # new_user_fullname dans l'ancien fcpi.py, identiques pour chaque cible).
    structured_field_templates_json = db.Column(db.Text, nullable=True)

    def get_structured_templates(self):
        if not self.structured_field_templates_json:
            return {}
        try:
            data = json.loads(self.structured_field_templates_json)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    fields = db.relationship('FormField', backref='form', order_by='FormField.order_index',
                              cascade='all, delete-orphan')
    steps = db.relationship('FormWorkflowStep', backref='form', order_by='FormWorkflowStep.order_index',
                             cascade='all, delete-orphan')
    dispatch_targets = db.relationship('FormDispatchTarget', backref='form', order_by='FormDispatchTarget.id',
                                        cascade='all, delete-orphan')

    @property
    def submissions_count(self):
        return FormSubmission.query.filter_by(form_definition_id=self.id).count()

    def __repr__(self):
        return f'<FormDefinition {self.slug}>'


# Colonnes structurées de Ticket qu'un FormField peut alimenter directement
# (voir FormField.maps_to_ticket_field). Sous-ensemble des colonnes "libres"
# du modèle Ticket déjà utilisées par les anciens modules (FCPI, tickets
# standard) — pas daf_* qui sont propres au circuit DAF hors moteur.
TICKET_FIELD_MAPPING_CHOICES = [
    'hostname', 'tel_demandeur', 'materiel_list', 'new_user_acces',
    'lieu_installation', 'destinataire_materiel', 'new_user_fullname',
    'new_user_service', 'new_user_date', 'service_demandeur',
]


class FormField(db.Model):
    __tablename__ = 'form_fields'
    id = db.Column(db.Integer, primary_key=True)
    form_definition_id = db.Column(db.Integer, db.ForeignKey('form_definitions.id'), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(150), nullable=False)
    field_type = db.Column(db.Enum(FormFieldType), nullable=False)
    is_required = db.Column(db.Boolean, default=False)
    options_json = db.Column(db.Text, nullable=True)
    help_text = db.Column(db.String(255), nullable=True)
    order_index = db.Column(db.Integer, default=0)

    # Visibilité conditionnelle : ce champ n'apparaît que si condition_field a
    # une certaine valeur. Pour un condition_field de type CHECKBOX,
    # condition_values_json est ignoré (visible si coché). Pour SELECT, visible
    # si la valeur soumise fait partie de condition_values_json (liste JSON —
    # plusieurs valeurs déclenchantes possibles, ex: CDI/Mutation/Détachement
    # déclenchent tous "date de prise de poste"). Pour MULTI_SELECT, visible si
    # au moins une valeur soumise fait partie de la liste. None/vide =
    # toujours visible (comportement par défaut, inchangé).
    condition_field_id = db.Column(db.Integer, db.ForeignKey('form_fields.id'), nullable=True)
    condition_values_json = db.Column(db.Text, nullable=True)
    condition_field = db.relationship('FormField', remote_side=[id])

    def get_condition_values(self):
        if not self.condition_values_json:
            return []
        try:
            return json.loads(self.condition_values_json) or []
        except Exception:
            return []

    # Si renseigné, la valeur soumise pour ce champ est copiée directement dans
    # la colonne correspondante du Ticket créé (en plus d'apparaître dans la
    # description générique), pour reproduire les anciens modules qui
    # alimentent des colonnes structurées (ex: FCPI -> materiel_list,
    # new_user_acces...). Doit être une des clés de TICKET_FIELD_MAPPING_CHOICES.
    maps_to_ticket_field = db.Column(db.String(50), nullable=True)

    __table_args__ = (db.UniqueConstraint('form_definition_id', 'name', name='uq_form_field_name'),)

    def get_options(self):
        if not self.options_json:
            return []
        try:
            return json.loads(self.options_json) or []
        except Exception:
            return []

    def is_visible(self, data):
        if not self.condition_field_id or not self.condition_field:
            return True
        ref = self.condition_field
        if ref.field_type == FormFieldType.CHECKBOX:
            return bool(data.get(ref.name))
        values = self.get_condition_values()
        submitted = data.get(ref.name)
        if isinstance(submitted, list):
            return bool(set(submitted) & set(values))
        return submitted in values

    def __repr__(self):
        return f'<FormField {self.name}>'


class FormWorkflowStep(db.Model):
    __tablename__ = 'form_workflow_steps'
    id = db.Column(db.Integer, primary_key=True)
    form_definition_id = db.Column(db.Integer, db.ForeignKey('form_definitions.id'), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(150), nullable=False)
    validator_role = db.Column(db.Enum(UserRole), nullable=True)
    validator_service = db.Column(db.Enum(ServiceType), nullable=True)
    # FIXED : validator_service est un service choisi par l'admin (cas "destinataire").
    # EMITTER : validator_service est ignoré, le service à matcher est celui du
    # demandeur lui-même (cas "émetteur" — Manager/Directeur du service du demandeur).
    service_source = db.Column(db.Enum(ServiceSource), default=ServiceSource.FIXED, nullable=False)
    # Liste JSON de UserRole (MANAGER/DIRECTEUR/ADMIN) : si l'auteur de la
    # soumission a déjà l'un de ces rôles, cette étape est sautée automatiquement
    # (ex: un Directeur n'a pas besoin de la validation "équipe" de sa propre
    # demande). Vide par défaut = jamais sautée, comportement inchangé.
    skip_for_author_roles_json = db.Column(db.Text, default='[]')

    def get_skip_roles(self):
        if not self.skip_for_author_roles_json:
            return []
        try:
            return json.loads(self.skip_for_author_roles_json) or []
        except Exception:
            return []

    def is_skipped_for(self, user):
        if not user:
            return False
        return str(user.role.value) in self.get_skip_roles()

    def __repr__(self):
        return f'<FormWorkflowStep {self.label}>'


class FormDispatchTarget(db.Model):
    """Un service qui reçoit un Ticket une fois la soumission terminée (toutes
    les étapes validées, ou immédiatement si le formulaire n'a aucune étape).
    Un formulaire peut avoir plusieurs destinataires (ex: FCPI -> DRH+INFO+SECU
    systématiques, +IMAGO conditionnel). Aucun destinataire = pas de Ticket créé,
    juste DONE + notification de l'auteur."""
    __tablename__ = 'form_dispatch_targets'
    id = db.Column(db.Integer, primary_key=True)
    form_definition_id = db.Column(db.Integer, db.ForeignKey('form_definitions.id'), nullable=False)
    label = db.Column(db.String(100), nullable=False)
    target_service = db.Column(db.Enum(ServiceType), nullable=False)
    # None = toujours dispatché. Sinon, selon le type de condition_field :
    # CHECKBOX -> dispatché si coché (condition_values_json ignoré) ;
    # SELECT/MULTI_SELECT -> dispatché si la valeur soumise fait partie de
    # condition_values_json (liste JSON — un même destinataire peut être visé
    # par plusieurs valeurs, ex: DRH-PAIE_CARRIERE reçoit "Paie", "Carrière",
    # "Contrat", "Avenant"... tandis que DRH-RECRUTEMENT_FORMATION reçoit
    # aussi "Contrat"/"Avenant" -> une soumission peut dispatcher vers
    # plusieurs destinataires à la fois selon la valeur choisie).
    condition_field_id = db.Column(db.Integer, db.ForeignKey('form_fields.id'), nullable=True)
    condition_field = db.relationship('FormField')
    condition_values_json = db.Column(db.Text, nullable=True)

    def get_condition_values(self):
        if not self.condition_values_json:
            return []
        try:
            return json.loads(self.condition_values_json) or []
        except Exception:
            return []

    # Liste JSON des noms de champs FILE/MULTI_FILE à copier dans le Ticket créé
    # pour ce destinataire. None/vide = tous les fichiers de la soumission
    # (comportement par défaut, inchangé) — permet un routage sélectif comme
    # l'ancien FCPI (CV+fiche de poste -> DRH, photo -> SECU, rien -> INFO/IMAGO).
    included_file_fields_json = db.Column(db.Text, nullable=True)

    # Liste JSON des noms de champs FormField (avec maps_to_ticket_field défini)
    # à appliquer sur le Ticket créé pour ce destinataire. None = tous les champs
    # mappés (comportement par défaut, inchangé) ; liste (même vide) = scoping
    # explicite par destinataire — même principe que included_file_fields_json,
    # pour reproduire l'ancien FCPI (materiel_list/new_user_acces/
    # lieu_installation/destinataire_materiel seulement sur INFO, lieu_installation
    # seul sur SECU, rien sur DRH/IMAGO). Sans ce scoping, un champ mappé
    # s'appliquait à TOUS les tickets d'une soumission multi-destinataires.
    included_mapped_fields_json = db.Column(db.Text, nullable=True)

    # Liste JSON des noms de champs à inclure dans la description générique
    # auto-générée du Ticket (celle utilisée quand ticket_description_template
    # n'est pas configuré) pour ce destinataire. None = tous les champs
    # (comportement par défaut, inchangé) ; liste (même vide) = scoping
    # explicite — même principe que les deux scopings ci-dessus, pour éviter
    # qu'une donnée sensible d'une section (ex: DRH) apparaisse dans le texte
    # libre d'un ticket destiné à un autre service (ex: Sécurité).
    included_description_fields_json = db.Column(db.Text, nullable=True)

    # Personnalisation du Ticket créé pour ce destinataire — pour reproduire
    # fidèlement les anciens modules (ex: FCPI met "Nouvel Utilisateur" en
    # catégorie, un titre et une description sur mesure par service). Chaîne
    # avec placeholders $nom_du_champ (syntaxe string.Template), substitués par
    # les valeurs soumises. Vide/None = comportement générique par défaut.
    ticket_category_template = db.Column(db.String(100), nullable=True)
    ticket_title_template = db.Column(db.String(255), nullable=True)
    ticket_description_template = db.Column(db.Text, nullable=True)
    # Suffixe court (ex: "DRH", "INF") utilisé pour un uid de ticket lisible
    # (F<id soumission>-<suffixe>). None = uid opaque par défaut (F<id>-<id cible>).
    uid_suffix = db.Column(db.String(20), nullable=True)

    def is_satisfied(self, data):
        if not self.condition_field_id or not self.condition_field:
            return True
        ref = self.condition_field
        if ref.field_type == FormFieldType.CHECKBOX:
            return bool(data.get(ref.name))
        values = self.get_condition_values()
        submitted = data.get(ref.name)
        if isinstance(submitted, list):
            return bool(set(submitted) & set(values))
        return submitted in values

    def get_included_file_fields(self):
        """None = non configuré -> tous les fichiers (défaut). Une liste (même
        vide) = sélection explicite de champs fichier à inclure."""
        if self.included_file_fields_json is None:
            return None
        try:
            return json.loads(self.included_file_fields_json)
        except Exception:
            return None

    def get_included_mapped_fields(self):
        """None = non configuré -> tous les champs mappés (défaut). Une liste
        (même vide) = sélection explicite de champs (par nom) à appliquer sur
        le Ticket de ce destinataire."""
        if self.included_mapped_fields_json is None:
            return None
        try:
            return json.loads(self.included_mapped_fields_json)
        except Exception:
            return None

    def get_included_description_fields(self):
        """None = non configuré -> tous les champs (défaut). Une liste (même
        vide) = sélection explicite de champs à inclure dans la description
        générique auto-générée pour ce destinataire."""
        if self.included_description_fields_json is None:
            return None
        try:
            return json.loads(self.included_description_fields_json)
        except Exception:
            return None

    def __repr__(self):
        return f'<FormDispatchTarget {self.label}>'


class FormSubmission(db.Model):
    __tablename__ = 'form_submissions'
    id = db.Column(db.Integer, primary_key=True)
    # 100 = marge pour couvrir le pire cas "FRM-{slug jusqu'à 60}-{date}-{compteur}"
    # (slug de form_definitions autorisé jusqu'à 60 caractères, cf. migration
    # a1f3c9d07b22 — l'ancienne limite de 40 plantait sur les formulaires à
    # nom long, ex: "demande-cr-ation-de-formulaire").
    uid_public = db.Column(db.String(100), unique=True, index=True)
    form_definition_id = db.Column(db.Integer, db.ForeignKey('form_definitions.id'), nullable=False)
    form = db.relationship('FormDefinition')
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    author = db.relationship('User', foreign_keys=[author_id], backref='my_form_submissions')
    data_json = db.Column(db.Text, default='{}')
    current_step_index = db.Column(db.Integer, default=0)
    last_validated_at = db.Column(db.DateTime, nullable=True)
    validated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.Enum(FormSubmissionStatus), default=FormSubmissionStatus.IN_PROGRESS)
    refusal_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Ticket(s) généré(s) à la finalisation (un par FormDispatchTarget satisfait).
    # Liste d'ids JSON, même convention que DossierSejour.child_tickets_ids.
    ticket_ids_json = db.Column(db.Text, default='[]')

    files = db.relationship('FormSubmissionFile', backref='submission', cascade='all, delete-orphan')

    def get_data(self):
        if not self.data_json:
            return {}
        try:
            return json.loads(self.data_json) or {}
        except Exception:
            return {}

    def set_data(self, data_dict):
        self.data_json = json.dumps(data_dict)

    def get_files_for(self, field_name):
        return [f for f in self.files if f.field_name == field_name]

    def get_ticket_ids(self):
        if not self.ticket_ids_json:
            return []
        try:
            return json.loads(self.ticket_ids_json) or []
        except Exception:
            return []

    def add_ticket_id(self, ticket_id):
        ids = self.get_ticket_ids()
        ids.append(ticket_id)
        self.ticket_ids_json = json.dumps(ids)

    def get_tickets(self):
        ids = self.get_ticket_ids()
        if not ids:
            return []
        return Ticket.query.filter(Ticket.id.in_(ids)).all()

    @property
    def author_name(self):
        return self.author.username if self.author else "Utilisateur supprimé"

    @property
    def current_step(self):
        steps = self.form.steps
        if 0 <= self.current_step_index < len(steps):
            return steps[self.current_step_index]
        return None

    def __repr__(self):
        return f'<FormSubmission {self.uid_public}>'


class FormSubmissionFile(db.Model):
    __tablename__ = 'form_submission_files'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('form_submissions.id'), nullable=False)
    field_name = db.Column(db.String(60), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    stored_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<FormSubmissionFile {self.stored_filename}>'


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(20), default='info')
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'category': self.category,
            'link': self.link,
            'is_read': self.is_read,
            'timestamp': self.timestamp.isoformat() + 'Z'
        }


# --- Lot 5 : délais et pilotage (paramètres applicatifs + trace d'escalade) ---

class AppSetting(db.Model):
    """Paramètre applicatif simple clé/valeur (texte), modifiable sur
    /admin/pilotage. Les valeurs par défaut et les accesseurs typés sont dans
    app/pilotage.py (get_setting / set_setting)."""
    __tablename__ = 'app_settings'
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<AppSetting {self.key}={self.value!r}>'


class EscalationTrace(db.Model):
    """Trace d'un e-mail d'escalade envoyé (scripts/escalade_validations.py) :
    un enregistrement par (demande, niveau, jour) — c'est l'anti-doublon qui
    garantit qu'un même niveau n'est pas renvoyé deux fois le même jour pour
    la même demande."""
    __tablename__ = 'escalation_traces'
    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(20), nullable=False)      # 'ticket' | 'submission'
    item_id = db.Column(db.Integer, nullable=False)
    level = db.Column(db.String(20), nullable=False)          # 'rappel' | 'directeur'
    sent_on = db.Column(db.Date, nullable=False, index=True)  # jour d'envoi
    recipients = db.Column(db.Text, nullable=True)            # e-mails, séparés par des virgules
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('item_type', 'item_id', 'level', 'sent_on', name='uq_escalation_trace_day'),
    )

    def __repr__(self):
        return f'<EscalationTrace {self.item_type}#{self.item_id} {self.level} {self.sent_on}>'


# --- Lot 8 : journal d'audit (reporting et conformité) ---
class AuditLog(db.Model):
    """Une ligne par action sensible (validation, refus, clôture, affectation,
    connexion, gestion des comptes/formulaires, purge RGPD…). Alimentée
    uniquement via app/audit.py::log_action, qui ne fait jamais échouer
    l'action tracée. `username` est une copie : la ligne reste lisible même si
    le compte est supprimé plus tard (user_id passe alors à NULL)."""
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    username = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(40), nullable=False, index=True)   # ex: ticket.validate, auth.login_failed
    target_type = db.Column(db.String(40), nullable=True)            # ex: Ticket, FormSubmission, User
    target_id = db.Column(db.Integer, nullable=True, index=True)
    target_ref = db.Column(db.String(100), nullable=True)            # uid lisible (uid_public, username, slug)
    details = db.Column(db.String(500), nullable=True)
    ip = db.Column(db.String(45), nullable=True)

    def __repr__(self):
        return f'<AuditLog {self.action} {self.target_ref}>'
