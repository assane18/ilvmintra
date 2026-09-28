from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, send_file
from flask_login import login_required, current_user
from app.models import Ticket, ServiceType, TicketStatus, UserRole, TicketMessage, Materiel, Pret, Notification, User, Recruitment, RecruitmentStatus
from app import db
# --- IMPORT DES FONCTIONS EMAIL (AJOUTÉ) ---
from app.emails import send_service_alert, send_assignment_notification, send_message_notification, send_closure_notification
# -------------------------------------------
from datetime import datetime
import pytz
import json
import os
import io
import socket
import statistics
from collections import defaultdict, Counter
from dateutil.relativedelta import relativedelta
import pandas as pd
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps

tickets_bp = Blueprint('tickets', __name__)

def get_paris_time():
    paris_tz = pytz.timezone('Europe/Paris')
    # On prend l'heure de Paris, et on retire l'info TZ pour le stockage naïf en DB
    return datetime.now(paris_tz).replace(tzinfo=None)

# --- HELPERS ---

def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0'
        return response
    return no_cache

def create_notification(user, message, category='info', link=None):
    if user:
        try:
            n = Notification(user=user, message=message, category=category, link=link)
            db.session.add(n)
        except: pass

def get_hostname_from_ip(ip_address):
    try: return socket.gethostbyaddr(ip_address)[0]
    except: return ip_address

def notify_solvers_new_ticket(ticket):
    """Notifications in-app pour les solvers/admins concernés par un nouveau
    ticket PENDING (prise en charge directe, sans étape de validation) —
    factorisé pour être appelé aussi bien par la création historique
    (new_ticket) que par le moteur de formulaires (forms.py::
    _create_tickets_from_submission), qui ne créait jusqu'ici que l'alerte
    email (send_service_alert) sans notification in-app."""
    service_enum = ticket.target_service
    uid = ticket.uid_public
    solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
    for s in solvers:
        if s.role == UserRole.ADMIN:
            create_notification(s, f"Nouveau ticket : {uid}", 'info', url_for('tickets.solver_dashboard'))
            continue

        allowed = s.get_allowed_services()
        if service_enum == ServiceType.IMAGO:
            if 'IMAGO' in allowed or 'GS-IMAGO' in allowed:
                create_notification(s, f"Urgence Imago : {uid}", 'warning', url_for('tickets.solver_dashboard'))
        else:
            target_str = str(service_enum.value) if hasattr(service_enum, 'value') else str(service_enum)
            if target_str in allowed or service_enum.name in allowed:
                create_notification(s, f"Nouveau ticket : {uid}", 'info', url_for('tickets.solver_dashboard'))

def safe_role_str(user):
    if not user or not user.role: return ""
    if hasattr(user.role, 'value'): return str(user.role.value).upper()
    return str(user.role).upper()

def check_permission(required_roles):
    try:
        current_role = safe_role_str(current_user)
        if 'ADMIN' in current_role: return True
        for req in required_roles:
            if req in current_role: return True
    except: return False
    return False

# --- HELPER EMAILS (AJOUTÉ) ---
def get_service_emails(service_enum):
    """ Récupère les emails de tous les membres du service cible """
    # On récupère les tech, managers, directeurs et admins
    staff = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN])).all()
    emails = []
    
    # On gère le cas où service_enum est une string ou une Enum
    target_val = service_enum.value if hasattr(service_enum, 'value') else str(service_enum)
    target_name = service_enum.name if hasattr(service_enum, 'name') else str(service_enum)
    
    for u in staff:
        if u.email and u.is_active:
            # On regarde si l'utilisateur a ce service dans ses droits
            user_services = u.get_allowed_services() # Renvoie une liste ['INFORMATIQUE', 'DAF']
            # Si le service est dans la liste ou si c'est un ADMIN global
            if target_val in user_services or target_name in user_services or "ADMIN" in str(u.role.value):
                emails.append(u.email)
    
    return list(set(emails)) # set() pour éviter les doublons
# ------------------------------

# --- ROUTES ---
@tickets_bp.route('/new/<service_name>', methods=['GET', 'POST'])
@login_required
@nocache
def new_ticket(service_name):
    
    # --- RECUPERATION DU TYPE DE DEMANDE (DAF Délégation) ---
    ticket_type = request.args.get('type', '')
    is_delegation = (service_name == 'DAF' and ticket_type == 'delegation')

    # --- 1. SÉCURITÉ ---
    role = str(current_user.role.value).upper()
    
    # Sécurité Matériel
    if service_name.upper() == 'MATERIEL':
        if 'MANAGER' not in role and 'DIRECTEUR' not in role and 'ADMIN' not in role:
            return render_template('errors/catdance.html'), 403

    # SÉCURITÉ DÉLÉGATION DAF (Ta demande spécifique)
    if is_delegation:
        if 'MANAGER' not in role and 'DIRECTEUR' not in role and 'ADMIN' not in role:
            # Si pas manager/directeur -> CATDANCE
            return render_template('errors/catdance.html'), 403

    # --- 2. DÉTERMINATION DU SERVICE ---
    if service_name.upper() == 'MATERIEL':
        service_enum = ServiceType.INFO 
    else:
        try:
            service_enum = ServiceType[service_name.upper()]
        except KeyError:
            flash(f"Service {service_name} inconnu.", "danger")
            return redirect(url_for('main.user_portal'))

    user_origins = current_user.get_origin_services()

    if request.method == 'POST':
        category = request.form.get('category_ticket', 'Standard')
        title = request.form.get('title')
        description = request.form.get('description')

        # ... (Logique DRH/Matériel existante inchangée) ...
        if service_name == 'DRH':
            cat_drh = request.form.get('titre_drh_select')
            if cat_drh == 'Autre':
                title = f"[DRH] {request.form.get('titre_drh_autre')}"
                category = "Demande RH"
            else:
                title = f"[DRH] {cat_drh}"
                category = cat_drh
        
        elif service_name.upper() == 'MATERIEL':
            title = request.form.get('title')
            category = "Demande Matériel"
        
        # LOGIQUE DAF
        if service_name == 'DAF':
            if is_delegation:
                category = 'Bon de Commande (Délégation)'
            elif category == 'Bon de Commande':
                # Cas standard
                pass
            
            fournisseur = request.form.get('daf_fournisseur_nom', 'Inconnu')
            title = f"Bon de Commande - {fournisseur}"
            description = request.form.get('description_daf', '')
        
        if service_name == 'IMAGO':
            category = 'Dépannage Imago'

        # ... (Reste de la logique hostname/origin inchangée) ...
        selected_origin = request.form.get('selected_origin')
        if not selected_origin:
            selected_origin = user_origins[0] if user_origins else "INCONNU"
            
        hostname_saisi = request.form.get('hostname')
        final_hostname = hostname_saisi if hostname_saisi else get_hostname_from_ip(request.remote_addr)

        # --- DAF Lignes & CALCUL TOTAL ---
        daf_lignes = []
        total_ttc = 0.0
        
        if service_name == 'DAF':
            for i in range(1, 51):
                des = request.form.get(f'daf_designation_{i}')
                if des: 
                    try:
                        ligne_total = float(request.form.get(f'daf_total_{i}', 0))
                        total_ttc += ligne_total
                    except: pass
                    
                    daf_lignes.append({
                        'designation': des, 
                        'ref': request.form.get(f'daf_ref_{i}'), 
                        'qte': request.form.get(f'daf_qte_{i}'), 
                        'pu': request.form.get(f'daf_pu_{i}'), 
                        'total': request.form.get(f'daf_total_{i}')
                    })

            # --- CONSTRAINT CHECK (HT 380€ / TTC 400€) ---
            if is_delegation:
                # On utilise 'daf_type_prix' pour être raccord avec le reste du formulaire
                tax_type = request.form.get('daf_type_prix', 'TTC') 
                limit = 380 if tax_type == 'HT' else 400
                
                # On utilise >= pour bloquer pile à la limite si tu veux être strict
                if total_ttc > limit:
                    flash(f"Erreur : Le montant total ({total_ttc}€) dépasse la limite de {limit}€ {tax_type} pour une délégation.", "danger")
                    return redirect(url_for('tickets.new_ticket', service_name='DAF', type='delegation'))


        # --- WORKFLOW ---
        status = TicketStatus.VALIDATION_N1 

        if is_delegation:
            # WORKFLOW SPÉCIFIQUE : On saute la validation N1/N2
            # On envoie direct en PENDING (Pour que le service DAF le voit et le traite)
            status = TicketStatus.PENDING
        
        elif (service_enum == ServiceType.INFO and category in ["Standard", "Incident Standard"]) or (service_enum == ServiceType.IMAGO):
            status = TicketStatus.PENDING
        
        elif service_name == 'DRH':
            status = TicketStatus.PENDING

        elif service_name.upper() == 'MATERIEL':
            status = TicketStatus.VALIDATION_N2

        elif service_name.upper() == 'DAF' and not is_delegation:
            # DAF standard (bon de commande, pas délégation) : un Directeur
            # d'un AUTRE service (ex: DRH) doit suivre exactement le même
            # circuit DAF que tout le monde (préparation par un solver DAF,
            # validation Manager DAF, signature Directeur DAF) — seule sa
            # propre validation hiérarchique (N1, qui reviendrait à se
            # valider lui-même) est inutile et donc sautée. Avant ce correctif,
            # le code envoyait ces demandes en VALIDATION_N2 puis, une fois
            # validées, sautait directement à DAF_SIGNATURE — court-circuitant
            # entièrement la préparation par le solver et la validation
            # Manager DAF (confirmé en recette le 2026-09-18).
            if role in (UserRole.DIRECTEUR, UserRole.ADMIN):
                status = TicketStatus.PENDING
            else:
                status = TicketStatus.VALIDATION_N1

        else:
            # Workflow Standard
            if role == UserRole.USER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.MANAGER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.DIRECTEUR: status = TicketStatus.VALIDATION_N2
            elif role == UserRole.ADMIN: status = TicketStatus.PENDING
            else: status = TicketStatus.VALIDATION_N1

        # UID
        today_str = datetime.now().strftime('%Y%m%d')
        base_query = Ticket.query.filter(Ticket.uid_public.like(f"{today_str}%"))
        count = base_query.count() + 1
        uid = f"{today_str}-{str(count).zfill(3)}"
        
        # Fichiers
        daf_files = []
        daf_rib_filename = None
        
        if request.files:
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', uid)
            
            # Screenshot
            screenshot_file = request.files.get('screenshot')
            if screenshot_file and screenshot_file.filename != '':
                try:
                    os.makedirs(upload_path, exist_ok=True)
                    s_filename = secure_filename(f"CAPTURE_{screenshot_file.filename}")
                    screenshot_file.save(os.path.join(upload_path, s_filename))
                    daf_files.append(s_filename)
                except Exception as e:
                    print(f"Erreur upload screenshot: {e}")

            if service_name == 'DAF':
                os.makedirs(upload_path, exist_ok=True)
                for i in range(1, 5):
                    file = request.files.get(f'devis_{i}')
                    if file and file.filename != '':
                        try:
                            filename = secure_filename(file.filename)
                            file.save(os.path.join(upload_path, filename))
                            daf_files.append(filename)
                        except: pass
                
                file_rib = request.files.get('daf_rib')
                if file_rib and file_rib.filename != '':
                    try:
                        daf_rib_filename = secure_filename(f"RIB_{file_rib.filename}")
                        file_rib.save(os.path.join(upload_path, daf_rib_filename))
                    except: pass

        supplier_status = request.form.get('supplier_status')
        is_new_supplier = True if supplier_status == 'new' else False

        t = Ticket(
            title=title,
            description=description,
            author=current_user,
            target_service=service_enum,
            status=status,
            uid_public=uid,
            category_ticket=category,
            created_at=get_paris_time(),
            service_demandeur=selected_origin,
            tel_demandeur=request.form.get('tel_demandeur'),
            hostname=final_hostname,
            lieu_installation=request.form.get('lieu_installation_user') or request.form.get('lieu_installation_mat'),
            daf_lieu_livraison=request.form.get('daf_lieu_livraison'),
            daf_fournisseur_nom=request.form.get('daf_fournisseur_nom'),
            daf_fournisseur_email=request.form.get('daf_fournisseur_email'),
            daf_type_prix=request.form.get('daf_type_prix'),
            daf_uf=request.form.get('daf_uf'),
            daf_budget_affecte=request.form.get('daf_budget'),
            daf_new_supplier=is_new_supplier,
            daf_siret=request.form.get('daf_siret'),
            daf_fournisseur_tel_comment=request.form.get('daf_fournisseur_tel'),
            daf_rib_file=daf_rib_filename,
            daf_lignes_json=json.dumps(daf_lignes),
            daf_files_json=json.dumps(daf_files)
        )
        
        try:
            db.session.add(t)
            db.session.commit()
            
            # --- EMAIL ALERT (AJOUTÉ) ---
            recipients = get_service_emails(service_enum)
            if recipients:
                send_service_alert(t, recipients)
            # ----------------------------

        except Exception as e:
            db.session.rollback()
            flash(f"Erreur DB: {e}", "danger")
            return redirect(url_for('main.user_portal'))

        # NOTIFICATIONS
        if status == TicketStatus.VALIDATION_N1:
            managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
            for mgr in managers:
                if selected_origin in mgr.get_origin_services():
                    create_notification(mgr, f"Validation requise : {uid}", 'warning', url_for('tickets.manager_dashboard'))
                    
        elif status == TicketStatus.VALIDATION_N2:
             # Généralisé (2026-09-17) : seul MATERIEL était couvert avant,
             # tout autre ticket créé directement en N2 (ex: un Directeur qui
             # saute sa propre validation N1) ne notifiait personne en
             # interne — trouvé lors de l'analyse fonctionnelle complète.
             target_val = service_enum.value if hasattr(service_enum, 'value') else str(service_enum)
             target_name = service_enum.name if hasattr(service_enum, 'name') else str(service_enum)
             targets = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
             for u in targets:
                 allowed = u.get_allowed_services()
                 if target_val in allowed or target_name in allowed:
                     create_notification(u, f"Validation requise : {uid}", 'warning', url_for('tickets.manager_dashboard'))

        elif status == TicketStatus.PENDING:
            notify_solvers_new_ticket(t)

        flash(f'Demande {uid} enregistrée.', 'success')
        return redirect(url_for('main.user_portal'))

    return render_template('tickets/new_ticket.html', service=service_enum, service_name=service_name, user_origins=user_origins, is_delegation=is_delegation)


@tickets_bp.route('/view/<string:ticket_uid>', methods=['GET', 'POST'])
@login_required
@nocache
def view_ticket(ticket_uid):
    try:
        ticket = Ticket.query.filter_by(uid_public=ticket_uid).first_or_404()
        user_role = safe_role_str(current_user)
        target_svc = ticket.get_safe_target_service()
        
        # --- 1. DROITS DE LECTURE (Qui peut VOIR ?) ---
        can_view = False
        if 'ADMIN' in user_role: can_view = True
        elif ticket.author_id == current_user.id: can_view = True
        elif 'SOLVER' in user_role and target_svc in current_user.get_allowed_services(): can_view = True
        elif 'MANAGER' in user_role or 'DIRECTEUR' in user_role:
            if ticket.service_demandeur in current_user.get_origin_services(): can_view = True
            if target_svc in current_user.get_allowed_services(): can_view = True
        
        if not can_view:
            flash("Accès non autorisé.", "warning")
            return redirect(url_for('main.user_portal'))

        # --- 2. DROITS DE GESTION (Qui peut ASSIGNER/TRAITER ?) ---
        can_manage_ticket = False
        
        # A. Je ne suis PAS l'auteur (sauf si je suis Admin)
        # Ceci est la règle d'or : Manager ou pas, si c'est ma demande, je ne touche pas à l'assignation.
        is_author = (ticket.author_id == current_user.id)
        
        if is_author and 'ADMIN' not in user_role:
            can_manage_ticket = False
        else:
            # B. Je suis Admin -> OUI
            if 'ADMIN' in user_role:
                can_manage_ticket = True
            
            # C. Je suis Tech/Manager/Directeur DU BON SERVICE -> OUI
            elif any(r in user_role for r in ['SOLVER', 'MANAGER', 'DIRECTEUR']):
                
                # --- LOGIQUE ROBUSTE DE COMPARAISON DE SERVICE ---
                # On compare toutes les variantes possibles (Nom, Valeur)
                
                # 1. On prépare les tags du ticket (ex: ['INFO', 'INFORMATIQUE'])
                ticket_tags = set()
                if hasattr(target_svc, 'value'): ticket_tags.add(str(target_svc.value))
                if hasattr(target_svc, 'name'): ticket_tags.add(str(target_svc.name))
                ticket_tags.add(str(target_svc))
                
                # 2. On prépare les tags de l'utilisateur (ses compétences)
                user_competencies = set()
                my_services = current_user.get_allowed_services()
                if my_services:
                    for s in my_services:
                        if hasattr(s, 'value'): user_competencies.add(str(s.value))
                        if hasattr(s, 'name'): user_competencies.add(str(s.name))
                        user_competencies.add(str(s))
                
                # 3. Intersection : Si un tag commun existe, c'est gagné
                if not ticket_tags.isdisjoint(user_competencies):
                    can_manage_ticket = True

        # --- 3. MESSAGERIE ---
        if request.method == 'POST' and request.form.get('message'):
            msg_content = request.form.get('message')
            msg = TicketMessage(content=msg_content, ticket=ticket, author=current_user)
            db.session.add(msg)
            
            # --- EMAIL NOTIFICATION MESSAGE (AJOUTÉ) ---
            # Cas 1: L'auteur écrit -> On notifie le technicien (s'il y en a un)
            if ticket.solver and current_user.id == ticket.author_id:
                create_notification(ticket.solver, f"Message sur {ticket.uid_public}", 'warning', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
                send_message_notification(ticket, msg_content, ticket.solver)
            
            # Cas 2: Le technicien (ou autre) écrit -> On notifie l'auteur
            elif current_user.id != ticket.author_id:
                create_notification(ticket.author, f"Réponse sur {ticket.uid_public}", 'success', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
                send_message_notification(ticket, msg_content, ticket.author)
            # -------------------------------------------

            db.session.commit()
            return redirect(url_for('tickets.view_ticket', ticket_uid=ticket_uid))
        
        # --- 4. DATA SUPPLEMENTAIRE ---
        attached_files = []
        if ticket.daf_files_json:
            try: attached_files = json.loads(ticket.daf_files_json)
            except: pass
            
        solvers_available = []
        
        # Si j'ai le droit de gérer, je veux voir la liste des collègues compétents
        if can_manage_ticket and ('MANAGER' in user_role or 'DIRECTEUR' in user_role or 'ADMIN' in user_role):
            all_staff = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.MANAGER, UserRole.ADMIN])).all()
            
            # Pour remplir la liste, on utilise la même logique de comparaison large
            ticket_tags = set()
            if hasattr(target_svc, 'value'): ticket_tags.add(str(target_svc.value))
            if hasattr(target_svc, 'name'): ticket_tags.add(str(target_svc.name))
            ticket_tags.add(str(target_svc))
            
            for s in all_staff:
                if 'ADMIN' in str(s.role.value):
                    solvers_available.append(s)
                    continue
                
                staff_competencies = set()
                s_services = s.get_allowed_services()
                if s_services:
                    for serv in s_services:
                        if hasattr(serv, 'value'): staff_competencies.add(str(serv.value))
                        if hasattr(serv, 'name'): staff_competencies.add(str(serv.name))
                        staff_competencies.add(str(serv))
                
                if not ticket_tags.isdisjoint(staff_competencies):
                    solvers_available.append(s)

        return render_template('tickets/detail.html', 
                               ticket=ticket, 
                               attached_files=attached_files, 
                               solvers_available=solvers_available,
                               can_manage_ticket=can_manage_ticket)

    except Exception as e:
        flash(f"Erreur : {str(e)}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/set_rdv/<int:ticket_id>', methods=['POST'])
@login_required
def set_rdv(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    role = safe_role_str(current_user)
    user_services = current_user.get_allowed_services()
    is_rh = 'DRH' in user_services
    is_imago = 'IMAGO' in user_services
    if not (('SOLVER' in role and (is_rh or is_imago)) or 'ADMIN' in role):
         flash("Action réservée aux Solvers RH et Imago.", "danger")
         return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
         
    date_str = request.form.get('rdv_date')
    if date_str:
        try:
            t.rdv_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
            msg = TicketMessage(content=f"RDV proposé le : {t.rdv_date.strftime('%d/%m/%Y à %H:%M')}", ticket=t, author=current_user)
            db.session.add(msg)
            db.session.commit()
            flash("RDV fixé avec succès.", "success")
        except Exception as e:
            flash(f"Erreur format date: {e}", "danger")
            
    return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))


@tickets_bp.route('/manager/dashboard')
@login_required
@nocache
def manager_dashboard():
    try:
        role_str = safe_role_str(current_user)
        if not ('MANAGER' in role_str or 'DIRECTEUR' in role_str or 'ADMIN' in role_str):
            if 'SOLVER' in role_str: return redirect(url_for('tickets.solver_dashboard'))
            return render_template('errors/catdance.html'), 403
        
        my_origins = current_user.get_origin_services() 
        raw_targets = current_user.get_allowed_services()
        
        valid_service_names = [s.name for s in ServiceType] 
        valid_service_values = [s.value for s in ServiceType]
        
        my_targets = []
        if raw_targets:
            for t in raw_targets:
                if t == 'GS-DRH': my_targets.append('DRH') 
                elif t in valid_service_names: my_targets.append(t)
                elif t in valid_service_values: my_targets.append(t)
        
        tickets_n1 = []
        if my_origins: 
            tickets_n1 = Ticket.query.filter(
                Ticket.status == TicketStatus.VALIDATION_N1,
                Ticket.service_demandeur.in_(my_origins),
                Ticket.author_id != current_user.id
            ).all()

        tickets_n2 = []
        if my_targets:
            try:
                base_query = Ticket.query.filter(Ticket.target_service.in_(my_targets))
                
                if 'DAF' in my_targets:
                    if 'DIRECTEUR' in role_str:
                        candidates = base_query.filter(Ticket.status.in_([TicketStatus.VALIDATION_N2, TicketStatus.DAF_SIGNATURE])).all()
                    else: 
                        candidates = base_query.filter(Ticket.status.in_([TicketStatus.VALIDATION_N2, TicketStatus.VALIDATION_DAF_MANAGER])).all()
                else:
                    candidates = base_query.filter(Ticket.status == TicketStatus.VALIDATION_N2).all()
                tickets_n2 = candidates
            except Exception as e:
                tickets_n2 = []

        fcpi_requests = []
        user_services = current_user.get_allowed_services()
        is_rh_team = 'DRH' in user_services or 'GS-DRH' in user_services or 'RH' in user_services or 'ADMIN' in role_str

        if is_rh_team:
            try:
                if 'MANAGER' in role_str or 'ADMIN' in role_str:
                    mgr_fcpi = Recruitment.query.filter_by(status=RecruitmentStatus.WAITING_RH_MGR).all()
                    fcpi_requests.extend(mgr_fcpi)
                if 'DIRECTEUR' in role_str or 'ADMIN' in role_str:
                    dir_fcpi = Recruitment.query.filter_by(status=RecruitmentStatus.WAITING_RH_DIR).all()
                    fcpi_requests.extend(dir_fcpi)
            except Exception as e:
                print(f"Erreur FCPI: {e}")
        
        fcpi_requests = list({r.id: r for r in fcpi_requests}.values())
        fcpi_requests.sort(key=lambda x: x.created_at, reverse=True)

        # Formulaires génériques : une étape EMITTER (service du demandeur) est
        # l'équivalent d'une validation N1 hiérarchique ; une étape FIXED (service
        # choisi par l'admin) est l'équivalent d'une validation N2 technique.
        # On les insère donc directement dans les onglets N1/N2 existants plutôt
        # que dans un onglet séparé.
        from app.models import FormSubmission, FormSubmissionStatus, ServiceSource
        from app.decorators import can_validate_step
        pending_forms = FormSubmission.query.filter_by(status=FormSubmissionStatus.IN_PROGRESS).all()
        matching_forms = [
            s for s in pending_forms
            if s.current_step and can_validate_step(current_user, s.current_step, s)
        ]
        form_submissions_n1 = [s for s in matching_forms if s.current_step.service_source == ServiceSource.EMITTER]
        form_submissions_n2 = [s for s in matching_forms if s.current_step.service_source == ServiceSource.FIXED]
        form_submissions_n1.sort(key=lambda s: s.created_at, reverse=True)
        form_submissions_n2.sort(key=lambda s: s.created_at, reverse=True)

        # Tickets qui traînent dans les services gérés par ce manager/directeur
        # (PENDING/IN_PROGRESS créés il y a plus de 24h) — visibilité demandée
        # explicitement pour qu'un manager voie si son équipe laisse traîner
        # des tickets, sans avoir à aller consulter les stats.
        stale_tickets = []
        if my_targets:
            candidates = Ticket.query.filter(
                Ticket.target_service.in_(my_targets),
                Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS])
            ).all()
            stale_tickets = [t for t in candidates if t.is_stale]
            stale_tickets.sort(key=lambda t: t.created_at)

        return render_template('tickets/manager_dashboard.html',
                            tickets_n1=tickets_n1,
                            tickets_n2=tickets_n2,
                            fcpi_requests=fcpi_requests,
                            form_submissions_n1=form_submissions_n1,
                            form_submissions_n2=form_submissions_n2,
                            stale_tickets=stale_tickets)

    except Exception as e:
        flash(f"Erreur Dashboard: {e}", "danger")
        return redirect(url_for('main.user_portal'))


# --- STATISTIQUES (DIRECTEUR/ADMIN) ---

_SERVICE_NAME_TO_VALUE = {s.name: s.value for s in ServiceType}


def _canon_service(tok):
    """Normalise un token de service (parfois stocké en .name, parfois en
    .value selon l'endroit du code — incohérence préexistante) vers la forme
    .value canonique, pour pouvoir comparer/regrouper de façon fiable."""
    if tok is None:
        return None
    if hasattr(tok, 'value'):
        tok = tok.value
    return _SERVICE_NAME_TO_VALUE.get(tok, tok)


def _get_stats_scope(user):
    """Périmètre des services visibles pour le dashboard/export Statistiques.
    None = illimité (ADMIN). Sinon liste triée de services (valeurs
    ServiceType), union des services d'origine et des services gérés — même
    normalisation que manager_dashboard() (dont le cas spécial 'GS-DRH' ->
    'DRH', tickets.py:502-513), réutilisée ici pour ne jamais faire diverger
    la sécurité entre les deux dashboards."""
    if 'ADMIN' in safe_role_str(user):
        return None
    my_origins = user.get_origin_services() or []
    raw_targets = user.get_allowed_services() or []
    valid_names = [s.name for s in ServiceType]
    valid_values = [s.value for s in ServiceType]
    my_targets = []
    for t in raw_targets:
        if t == 'GS-DRH':
            my_targets.append('DRH')
        elif t in valid_names or t in valid_values:
            my_targets.append(t)
    combined = {_canon_service(t) for t in (list(my_origins) + my_targets)}
    combined.discard(None)
    return sorted(combined)


def _stats_period_bounds(period, start_str, end_str, now):
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == 'this_month':
        return month_start, today_end
    if period == 'last_3_months':
        return month_start - relativedelta(months=2), today_end
    if period == 'this_year':
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), today_end
    if period == 'custom' and start_str and end_str:
        try:
            start = datetime.strptime(start_str, '%Y-%m-%d')
            end = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            return start, end
        except ValueError:
            pass
    # défaut : last_12_months
    return month_start - relativedelta(months=11), today_end


def _empty_stats_entry():
    return {
        'received': 0, 'closed': 0,
        'assign_avg_h': None, 'assign_median_h': None,
        'close_avg_h': None, 'close_median_h': None,
        'status_counts': {}, 'refusal_rate': 0,
        'top_categories': [], 'monthly': {},
    }


def _compute_stats(scope_services, period_start, period_end, monthly_start, monthly_end):
    """Calcule les métriques par service (KPI de la période + évolution
    mensuelle sur sa propre fenêtre, indépendante de `period`). Deux requêtes
    "lean" (with_entities, pas l'ORM complet) plutôt qu'une par service, pour
    éviter le N+1 — voir plan Statistiques. scope_services=None -> illimité."""
    window_start = min(period_start, monthly_start)
    window_end = max(period_end, monthly_end)

    q_created = Ticket.query.with_entities(
        Ticket.target_service, Ticket.status, Ticket.created_at,
        Ticket.assigned_at, Ticket.category_ticket,
    ).filter(Ticket.created_at.between(window_start, window_end))
    if scope_services is not None:
        q_created = q_created.filter(Ticket.target_service.in_(scope_services))

    q_closed = Ticket.query.with_entities(
        Ticket.target_service, Ticket.created_at, Ticket.closed_at,
    ).filter(Ticket.status == TicketStatus.DONE, Ticket.closed_at.between(window_start, window_end))
    if scope_services is not None:
        q_closed = q_closed.filter(Ticket.target_service.in_(scope_services))

    def label(v):
        return v.value if hasattr(v, 'value') else str(v)

    created_by_service = defaultdict(list)
    for row in q_created.all():
        created_by_service[label(row.target_service)].append(row)

    closed_by_service = defaultdict(list)
    for row in q_closed.all():
        closed_by_service[label(row.target_service)].append(row)

    services = sorted(set(created_by_service) | set(closed_by_service))
    stats = {}
    for svc in services:
        c_rows = [r for r in created_by_service[svc] if period_start <= r.created_at <= period_end]
        d_rows = [r for r in closed_by_service[svc] if period_start <= r.closed_at <= period_end]

        assign_delays = [(r.assigned_at - r.created_at).total_seconds() / 3600 for r in c_rows if r.assigned_at]
        close_delays = [(r.closed_at - r.created_at).total_seconds() / 3600 for r in d_rows]
        status_counts = Counter(label(r.status) for r in c_rows)
        refused = status_counts.get(TicketStatus.REFUSED.value, 0)
        top_categories = Counter(r.category_ticket or 'Non renseigné' for r in c_rows).most_common(3)

        monthly = defaultdict(lambda: {'received': 0, 'closed': 0})
        for r in created_by_service[svc]:
            if monthly_start <= r.created_at <= monthly_end:
                monthly[r.created_at.strftime('%Y-%m')]['received'] += 1
        for r in closed_by_service[svc]:
            if monthly_start <= r.closed_at <= monthly_end:
                monthly[r.closed_at.strftime('%Y-%m')]['closed'] += 1

        stats[svc] = {
            'received': len(c_rows),
            'closed': len(d_rows),
            'assign_avg_h': round(statistics.mean(assign_delays), 1) if assign_delays else None,
            'assign_median_h': round(statistics.median(assign_delays), 1) if assign_delays else None,
            'close_avg_h': round(statistics.mean(close_delays), 1) if close_delays else None,
            'close_median_h': round(statistics.median(close_delays), 1) if close_delays else None,
            'status_counts': dict(status_counts),
            'refusal_rate': round(refused / len(c_rows) * 100, 1) if c_rows else 0,
            'top_categories': top_categories,
            'monthly': dict(sorted(monthly.items())),
        }
    return stats


# Sous-ensemble "Services Supports" de ServiceType (models.py:26-34) — les
# catégories techniques susceptibles de recevoir des tickets (portail,
# FCPI, Séjour...), à distinguer des ~30 "Services Établissements" (unités
# organisationnelles, jamais des cibles de ticket). Certains support n'ont
# pas encore de ticket réel (ex: SECU, TECH) mais restent des options
# pertinentes du filtre — pas seulement ceux ayant déjà des données.
_SUPPORT_SERVICES = [ServiceType.INFO, ServiceType.DAF, ServiceType.GEN, ServiceType.TECH,
                      ServiceType.DRH, ServiceType.SECU, ServiceType.AUTRE, ServiceType.IMAGO]


def _relevant_services():
    """Services pertinents pour le filtre du dashboard Statistiques : union
    des Services Supports (toujours proposés, même sans ticket) et de tout
    autre service ayant déjà reçu un ticket (ex: SG, catégorisé "établissement"
    dans l'enum mais réellement utilisé par le dispatch Séjour)."""
    values = {s.value for s in _SUPPORT_SERVICES}
    rows = db.session.query(Ticket.target_service).distinct().all()
    for (svc,) in rows:
        if svc is not None:
            values.add(svc.value if hasattr(svc, 'value') else str(svc))
    return sorted(values)


def _resolve_display_services(scope, requested_list):
    """Applique la sélection explicite (?services=A&services=B, une case à
    cocher = un paramètre) par-dessus le périmètre autorisé. Intersection
    stricte côté serveur pour un Directeur — ne jamais faire confiance à la
    liste cochée côté client."""
    requested = [_canon_service(s) for s in (requested_list or []) if s]
    if scope is not None:
        if requested:
            allowed = sorted(set(scope) & set(requested))
            if not allowed:
                flash("Aucun service sélectionné n'est dans votre périmètre.", "warning")
                allowed = sorted(scope)
        else:
            allowed = sorted(scope)
    else:
        allowed = sorted(set(requested)) if requested else None
    return allowed


@tickets_bp.route('/stats')
@login_required
@nocache
def stats_dashboard():
    if not check_permission(['DIRECTEUR']):
        return render_template('errors/catdance.html'), 403

    scope = _get_stats_scope(current_user)
    if scope is not None and not scope:
        flash("Aucun service ne vous est actuellement assigné.", "warning")
        return render_template('tickets/stats_dashboard.html', sections=[], scope=[], period='last_12_months',
                                start='', end='', selected_services=[])

    period = request.args.get('period', 'last_12_months')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    requested_raw = request.args.getlist('services')

    now = get_paris_time()
    period_start, period_end = _stats_period_bounds(period, start_str, end_str, now)
    monthly_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - relativedelta(months=11))
    monthly_end = now

    display_services = _resolve_display_services(scope, requested_raw)

    stats = _compute_stats(display_services, period_start, period_end, monthly_start, monthly_end)

    if display_services is None:
        # ADMIN sans sélection explicite : uniquement les services ayant des
        # données sur la fenêtre, pour éviter ~30 sections vides.
        display_services = sorted(stats.keys())

    sections = []
    for svc in display_services:
        sections.append({'service': svc, **stats.get(svc, _empty_stats_entry())})

    return render_template(
        'tickets/stats_dashboard.html',
        sections=sections,
        scope=scope,
        all_services=_relevant_services() if scope is None else scope,
        period=period, start=start_str, end=end_str,
        selected_services=display_services or [],
        period_start=period_start, period_end=period_end,
    )


def _sanitize_sheet_name(name, used):
    """Nom de feuille Excel valide (31 car. max, sans : \\ / ? * [ ]) et
    unique dans le classeur (suffixe numérique en cas de collision après
    troncature)."""
    invalid = set(':\\/?*[]')
    cleaned = ''.join(c for c in str(name) if c not in invalid).strip() or 'Service'
    cleaned = cleaned[:31]
    base, n = cleaned, 1
    while cleaned in used:
        suffix = f'_{n}'
        cleaned = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(cleaned)
    return cleaned


@tickets_bp.route('/stats/export')
@login_required
def export_stats():
    if not check_permission(['DIRECTEUR']):
        return render_template('errors/catdance.html'), 403

    scope = _get_stats_scope(current_user)
    if scope is not None and not scope:
        flash("Aucun service ne vous est actuellement assigné.", "warning")
        return redirect(url_for('tickets.stats_dashboard'))

    period = request.args.get('period', 'last_12_months')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    requested_raw = request.args.getlist('services')

    now = get_paris_time()
    period_start, period_end = _stats_period_bounds(period, start_str, end_str, now)
    monthly_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - relativedelta(months=11))
    monthly_end = now

    # Re-validation stricte côté serveur — indépendante de ce qu'affichait la
    # page, jamais de confiance dans la liste transmise (surtout pour un
    # Directeur : ne jamais exporter un service hors de son périmètre).
    export_services = _resolve_display_services(scope, requested_raw)
    stats = _compute_stats(export_services, period_start, period_end, monthly_start, monthly_end)
    if export_services is None:
        export_services = sorted(stats.keys()) if stats else ([s.value for s in ServiceType])

    if not export_services:
        flash("Aucune donnée à exporter pour cette sélection.", "warning")
        return redirect(url_for('tickets.stats_dashboard'))

    # --- Feuille Résumé ---
    summary_rows = []
    for svc in export_services:
        s = stats.get(svc, _empty_stats_entry())
        top_cats = s['top_categories'] + [('', '')] * 3
        summary_rows.append({
            'Service': svc,
            'Periode': f"{period_start.strftime('%Y-%m-%d')} au {period_end.strftime('%Y-%m-%d')}",
            'Tickets_Recus': s['received'],
            'Tickets_Clotures': s['closed'],
            'Delai_Moyen_Assignation_h': s['assign_avg_h'],
            'Delai_Median_Assignation_h': s['assign_median_h'],
            'Delai_Moyen_Cloture_h': s['close_avg_h'],
            'Delai_Median_Cloture_h': s['close_median_h'],
            'Taux_Refus_%': s['refusal_rate'],
            'Top_Categorie_1': top_cats[0][0], 'Top_Categorie_2': top_cats[1][0], 'Top_Categorie_3': top_cats[2][0],
        })
    df_summary = pd.DataFrame(summary_rows)

    # --- Feuille Evolution_Mensuelle ---
    monthly_rows = []
    for svc in export_services:
        s = stats.get(svc, _empty_stats_entry())
        for month, vals in s['monthly'].items():
            monthly_rows.append({
                'Service': svc, 'Mois': month,
                'Tickets_Recus': vals['received'], 'Tickets_Clotures': vals['closed'],
            })
    df_monthly = pd.DataFrame(monthly_rows)

    # --- Détail des tickets bruts (union créés/clôturés sur la période) ---
    detail_tickets = Ticket.query.filter(
        Ticket.target_service.in_(export_services),
        db.or_(
            Ticket.created_at.between(period_start, period_end),
            db.and_(Ticket.status == TicketStatus.DONE, Ticket.closed_at.between(period_start, period_end)),
        )
    ).all()

    detail_by_service = defaultdict(list)
    for t in detail_tickets:
        assign_delay = round((t.assigned_at - t.created_at).total_seconds() / 3600, 1) if t.assigned_at else None
        close_delay = round((t.closed_at - t.created_at).total_seconds() / 3600, 1) if t.closed_at else None
        detail_by_service[t.get_safe_target_service()].append({
            'Reference': t.uid_public,
            'Date_Creation': t.created_at.strftime('%Y-%m-%d %H:%M'),
            'Date_Prise_en_charge': t.assigned_at.strftime('%Y-%m-%d %H:%M') if t.assigned_at else '',
            'Delai_Assignation_h': assign_delay,
            'Date_Cloture': t.closed_at.strftime('%Y-%m-%d %H:%M') if t.closed_at else '',
            'Delai_Cloture_h': close_delay,
            'Statut': t.get_safe_status(),
            'Categorie': t.category_ticket,
            'Titre': t.title,
            'Demandeur': t.author.fullname if t.author else '',
            'Resoluteur': t.solver.fullname if t.solver else '',
        })

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_summary.to_excel(writer, sheet_name='Résumé', index=False)
        if not df_monthly.empty:
            df_monthly.to_excel(writer, sheet_name='Evolution_Mensuelle', index=False)

        used_names = {'Résumé', 'Evolution_Mensuelle'}
        if len(export_services) > 15:
            # Trop de services pour une feuille par service (cas "tous les
            # services" côté Admin) : une seule feuille avec colonne Service.
            all_detail = []
            for svc in export_services:
                for row in detail_by_service.get(svc, []):
                    all_detail.append({'Service': svc, **row})
            pd.DataFrame(all_detail).to_excel(writer, sheet_name='Détail_Tous', index=False)
        else:
            for svc in export_services:
                rows = detail_by_service.get(svc, [])
                sheet_name = _sanitize_sheet_name(f'Détail_{svc}', used_names)
                pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)

    buffer.seek(0)
    filename = f'Statistiques_Tickets_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


def _can_validate_ticket(user, t):
    """Réplique l'éligibilité utilisée pour peupler manager_dashboard()
    (tickets_n1/tickets_n2) — qui jusqu'ici ne filtrait que l'AFFICHAGE, sans
    équivalent côté serveur dans manager_action(). Un appel direct à l'URL
    pouvait donc valider/refuser n'importe quel ticket sans aucun droit."""
    role_str = safe_role_str(user)
    if 'ADMIN' in role_str:
        return True
    if not ('MANAGER' in role_str or 'DIRECTEUR' in role_str):
        return False

    if t.status == TicketStatus.VALIDATION_N1:
        return t.service_demandeur in user.get_origin_services() and t.author_id != user.id

    if t.status in (TicketStatus.VALIDATION_N2, TicketStatus.VALIDATION_DAF_MANAGER):
        raw_targets = user.get_allowed_services()
        valid_names = [s.name for s in ServiceType]
        valid_values = [s.value for s in ServiceType]
        my_targets = []
        for tk in (raw_targets or []):
            if tk == 'GS-DRH':
                my_targets.append('DRH')
            elif tk in valid_names or tk in valid_values:
                my_targets.append(tk)

        target_val = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
        if target_val not in my_targets:
            return False

        if t.status == TicketStatus.VALIDATION_DAF_MANAGER:
            # Même règle que manager_daf_validate() : réservé au Manager DAF.
            return 'MANAGER' in role_str
        return True

    return False


@tickets_bp.route('/manager/action/<int:ticket_id>/<action>', methods=['GET', 'POST'])
@login_required
def manager_action(ticket_id, action):
    try:
        t = Ticket.query.get_or_404(ticket_id)

        if not _can_validate_ticket(current_user, t):
            flash("Droits insuffisants pour cette action.", "danger")
            return redirect(url_for('tickets.manager_dashboard'))

        if action == 'validate':
            if t.status == TicketStatus.VALIDATION_N1:
                if t.target_service == ServiceType.DAF: t.status = TicketStatus.PENDING
                else: t.status = TicketStatus.VALIDATION_N2
                
            elif t.status == TicketStatus.VALIDATION_N2:
                # DAF n'atteint plus jamais VALIDATION_N2 depuis le correctif
                # du 2026-09-18 (voir new_ticket) — un ticket DAF y arrivant
                # malgré tout (donnée historique, par ex.) suit désormais le
                # même chemin que tout le reste : retour en file DAF normale,
                # pas de raccourci vers la signature.
                t.status = TicketStatus.PENDING
                
            elif t.status == TicketStatus.VALIDATION_DAF_MANAGER:
                t.status = TicketStatus.DAF_SIGNATURE

            elif t.category_ticket == 'Demande Matériel' and t.status == TicketStatus.VALIDATION_N2:
                t.status = TicketStatus.PENDING

        elif action == 'refuse':
            reason = request.form.get('refusal_reason', 'Refusé.')
            msg = TicketMessage(content=f"Ticket REFUSÉ par {current_user.fullname}.\nMotif : {reason}", ticket=t, author=current_user)
            db.session.add(msg)
            create_notification(t.author, f"Votre ticket {t.uid_public} a été refusé.", 'danger', url_for('tickets.view_ticket', ticket_uid=t.uid_public))

            if t.target_service == ServiceType.DAF and t.status in [TicketStatus.VALIDATION_DAF_MANAGER]:
                t.status = TicketStatus.IN_PROGRESS 
            else:
                t.status = TicketStatus.REFUSED

        db.session.commit()
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur action: {e}", "danger")
        return redirect(url_for('tickets.manager_dashboard'))

@tickets_bp.route('/manager/daf_validate/<int:ticket_id>', methods=['POST'])
@login_required
def manager_daf_validate(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)
        role = safe_role_str(current_user)
        is_daf = 'DAF' in current_user.get_allowed_services()
        
        if not (is_daf and ('MANAGER' in role or 'ADMIN' in role)):
             flash("Action réservée au Manager DAF.", "danger")
             return redirect(url_for('tickets.manager_dashboard'))

        t.status = TicketStatus.DAF_SIGNATURE
        db.session.commit()
        flash("Validé par Manager DAF. En attente signature Directeur.", "success")
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur: {e}", "danger")
        return redirect(url_for('tickets.manager_dashboard'))

@tickets_bp.route('/solver/take/<int:ticket_id>')
@login_required
def take_ticket(ticket_id):
    try:
        if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): 
            flash("Droits insuffisants.", "danger")
            return redirect(url_for('main.user_portal'))
            
        t = Ticket.query.get_or_404(ticket_id)
        
        # --- SÉCURITÉ ANTI-AUTO-ATTRIBUTION ---
        if t.author_id == current_user.id:
            flash("Vous ne pouvez pas prendre en charge votre propre demande.", "warning")
            return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
        # --------------------------------------

        t.solver = current_user
        t.status = TicketStatus.IN_PROGRESS
        if not t.assigned_at:
            t.assigned_at = get_paris_time()
        create_notification(t.author, f"Pris en charge par {current_user.fullname}", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
        
        # --- EMAIL NOTIFICATION (AJOUTÉ) ---
        send_assignment_notification(t, current_user)
        send_message_notification(t, f"Votre ticket a été pris en charge par {current_user.fullname}", t.author)
        # -----------------------------------

        db.session.commit()
        return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
    except Exception as e:
        flash(f"Erreur prise en charge: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/daf_submit/<int:ticket_id>', methods=['POST'])
@login_required
def daf_solver_submit(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)

        # Même règle que l'affichage du bloc "Traitement DAF" dans
        # tickets/detail.html (ticket.solver_id == current_user.id).
        if t.solver_id != current_user.id and 'ADMIN' not in safe_role_str(current_user):
            flash("Seul le technicien en charge du ticket peut soumettre le bon.", "danger")
            return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

        if 'daf_prepared_file' in request.files:
            file = request.files['daf_prepared_file']
            if file and file.filename != '':
                filename = secure_filename(f"PREPA_{t.uid_public}_{file.filename}")
                upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', t.uid_public)
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, filename))
                
                t.daf_solver_file = filename
                
                # --- NOTIFICATION AU DEMANDEUR ---
                create_notification(
                    user=t.author, 
                    message=f"Un bon de commande a été ajouté à votre ticket {t.uid_public}.",
                    category='success',
                    link=url_for('tickets.view_ticket', ticket_uid=t.uid_public)
                )
                
                t.status = TicketStatus.VALIDATION_DAF_MANAGER 
                db.session.commit()
                flash("Bon transmis au Manager DAF pour validation.", "success")
        return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
    except Exception as e:
        flash(f"Erreur: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/director/daf_sign/<int:ticket_id>', methods=['POST'])
@login_required
def daf_director_sign(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)

        # Même règle que celle qui filtre les tickets DAF_SIGNATURE dans
        # manager_dashboard() : réservée à un Directeur (ou Admin) du service DAF.
        role_str = safe_role_str(current_user)
        is_daf = 'DAF' in current_user.get_allowed_services()
        if not (is_daf and ('DIRECTEUR' in role_str or 'ADMIN' in role_str)):
            flash("Signature réservée au Directeur DAF.", "danger")
            return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

        if 'daf_signed_file' in request.files:
            file = request.files['daf_signed_file']
            if file and file.filename != '':
                filename = secure_filename(f"SIGNE_{t.uid_public}_{file.filename}")
                upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', t.uid_public)
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, filename))
                t.daf_signed_file = filename
                t.status = TicketStatus.DONE
                t.closed_at = get_paris_time()

                # Notifier le gestionnaire (solver) que le bon signé est disponible
                if t.solver:
                    create_notification(
                        user=t.solver,
                        message=f"Le bon de commande {t.uid_public} a été signé par le Directeur. Dossier clôturé.",
                        category='success',
                        link=url_for('tickets.view_ticket', ticket_uid=t.uid_public)
                    )
                # Notifier le demandeur
                create_notification(
                    user=t.author,
                    message=f"Votre bon de commande {t.uid_public} a été signé et clôturé.",
                    category='success',
                    link=url_for('tickets.view_ticket', ticket_uid=t.uid_public)
                )
                db.session.commit()
                flash("Bon signé. Bon de commande clôturé et transmis au gestionnaire.", "success")
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/close/<int:ticket_id>', methods=['POST'])
@login_required
def close_ticket(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)

        # Même règle que celle qui conditionne l'affichage du bouton "Clôturer"
        # dans tickets/detail.html (ticket.solver_id == current_user.id) —
        # jusqu'ici absente côté serveur, donc n'importe quel utilisateur
        # connecté pouvait clôturer n'importe quel ticket par simple appel direct.
        if t.solver_id != current_user.id and 'ADMIN' not in safe_role_str(current_user):
            flash("Seul le technicien en charge du ticket peut le clôturer.", "danger")
            return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

        t.status = TicketStatus.DONE
        t.closed_at = get_paris_time()

        # --- NOTIFICATION CLOTURE ---
        create_notification(
            user=t.author,
            message=f"Votre ticket {t.uid_public} a été traité et clôturé.",
            category='success',
            link=url_for('tickets.view_ticket', ticket_uid=t.uid_public)
        )
        # --- EMAIL (AJOUTÉ) ---
        send_closure_notification(t)
        # ----------------------

        db.session.commit()

        # --- SUIVI AUTO SÉJOUR : si ce ticket est un enfant de séjour, vérifier si tout est terminé ---
        if t.uid_public and t.uid_public.startswith('SEJ-'):
            try:
                from app.models import DossierSejour, SejourStatus
                import json as _json
                sejours = DossierSejour.query.filter_by(status=SejourStatus.DISPATCHED).all()
                for sejour in sejours:
                    child_ids = sejour.get_child_tickets()
                    if t.id in child_ids:
                        children = Ticket.query.filter(Ticket.id.in_(child_ids)).all()
                        if children and all(c.status == TicketStatus.DONE for c in children):
                            sejour.status = SejourStatus.DONE
                            from app.models import Notification as Notif
                            n = Notif(
                                user=sejour.author,
                                message=f"Votre dossier de séjour {sejour.uid_public} a été entièrement traité par tous les services.",
                                category='success',
                                link=url_for('sejour.view_sejour', id=sejour.id)
                            )
                            db.session.add(n)
                            db.session.commit()
            except Exception:
                pass
        # ----------------------

        flash("Ticket clôturé avec succès.", "success")
        return redirect(url_for('tickets.solver_dashboard'))
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur fermeture: {e}", "danger")
        return redirect(url_for('main.user_portal'))
        
@tickets_bp.route('/solver/dashboard')
@login_required
@nocache
def solver_dashboard():
    try:
        if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']):
            return render_template('errors/catdance.html'), 403

        my_targets = current_user.get_allowed_services() 
        user_role = safe_role_str(current_user)
        
        if 'IMAGO' in user_role or 'GS-IMAGO' in user_role:
             if my_targets is None: my_targets = []
             if ServiceType.IMAGO not in my_targets:
                 my_targets.append(ServiceType.IMAGO)
        
        if user_role in ['MANAGER', 'DIRECTEUR'] and not my_targets:
             flash("Aucun service technique assigné.", "warning")
             return redirect(url_for('tickets.manager_dashboard'))

        query = Ticket.query.filter(Ticket.status != TicketStatus.DONE)
        
        tickets_pool = []
        if 'ADMIN' in user_role:
            tickets_pool = query.all()
        elif my_targets:
            tickets_all = query.all()
            for t in tickets_all:
                is_allowed = False
                t_svc_val = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
                for allowed_svc in my_targets:
                    a_svc_val = allowed_svc.value if hasattr(allowed_svc, 'value') else str(allowed_svc)
                    if t_svc_val == a_svc_val:
                        is_allowed = True
                        break
                if is_allowed:
                    tickets_pool.append(t)
        else:
            tickets_pool = []

        pending_states = ['EN_ATTENTE_TRAITEMENT', 'PENDING', 'VALIDATION_DAF_MANAGER']
        pending_tickets = []
        for t in tickets_pool:
            if t.solver_id is None:
                is_pending = False
                if t.status == TicketStatus.PENDING: is_pending = True
                else:
                    status_val = t.status.value if hasattr(t.status, 'value') else str(t.status)
                    if status_val in pending_states: is_pending = True
                if is_pending: pending_tickets.append(t)
        
        drh_enum = getattr(ServiceType, 'DRH', 'DRH') 

        # DRH générique + sous-services (DRH-PAIE_CARRIERE, ...) : les tickets
        # des sous-services portent une catégorie libre ($type_demande, ex:
        # "Paie") et ne tomberaient dans aucune autre file.
        def is_drh(t):
            val = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
            return val in ('DRH', 'GS-DRH') or val.startswith('DRH-')

        pool_imago = [t for t in pending_tickets if str(t.target_service) == 'IMAGO' or t.target_service == ServiceType.IMAGO]
        
        pool_standard = [
            t for t in pending_tickets 
            if (not t.category_ticket or t.category_ticket in ['Standard', 'Incident Standard', 'Demande RH']) 
            and str(t.target_service) != 'IMAGO' and t.target_service != ServiceType.IMAGO
            and not is_drh(t)
        ]
        
        pool_users = [t for t in pending_tickets if t.category_ticket == 'Nouvel Utilisateur']
        pool_materiel = [t for t in pending_tickets if t.category_ticket == 'Matériel' or t.category_ticket == 'Demande Matériel']

        pool_bons = [t for t in pending_tickets if t.category_ticket in ['Bon de Commande', 'Bon de Commande (Délégation)']]
        
        pool_drh = [t for t in pending_tickets if is_drh(t)]
        
        mine = Ticket.query.filter_by(solver_id=current_user.id, status=TicketStatus.IN_PROGRESS).all()
        
        hist_query = Ticket.query.filter_by(status=TicketStatus.DONE)
        history_all = hist_query.order_by(Ticket.closed_at.desc()).limit(20).all()
        
        if 'ADMIN' not in user_role and my_targets:
            history = []
            for t in history_all:
                t_svc_val = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
                for allowed_svc in my_targets:
                    a_svc_val = allowed_svc.value if hasattr(allowed_svc, 'value') else str(allowed_svc)
                    if t_svc_val == a_svc_val:
                        history.append(t)
                        break
        else:
            history = history_all

        stats = {
            'active': len(mine),
            'done': len(history),
            'pending': len(pending_tickets),
            'stock': Materiel.query.filter_by(statut='Disponible').count(),
            'prets': Pret.query.filter_by(statut_dossier='En cours').count()
        }
        
        team_solvers = User.query.filter(User.role == UserRole.SOLVER).all()

        return render_template('tickets/service_dashboard.html', 
                               stats=stats, 
                               pool_standard=pool_standard, 
                               pool_users=pool_users, 
                               pool_materiel=pool_materiel, 
                               pool_bons=pool_bons, 
                               pool_imago=pool_imago,
                               pool_drh=pool_drh,
                               mine=mine, 
                               history=history, 
                               solvers=team_solvers, 
                               services=ServiceType)
    except Exception as e:
        print(f"Error Solver Dash: {e}")
        return render_template('base.html', content=f"<h1>Erreur 500 Dashboard</h1><p>{e}</p>")

@tickets_bp.route('/historique', methods=['GET', 'POST'])
@login_required
@nocache
def historique_tickets():
    # 1. GESTION DE L'AJOUT MANUEL (POST)
    if request.method == 'POST':
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            count = Ticket.query.filter(Ticket.uid_public.like(f"{today_str}%")).count() + 1
            uid = f"{today_str}-{str(count).zfill(3)}"

            date_creation_str = request.form.get('date_creation')
            created_at = get_paris_time()
            if date_creation_str:
                try:
                    created_at = datetime.strptime(date_creation_str, '%Y-%m-%dT%H:%M')
                except:
                    pass

            my_services = current_user.get_allowed_services()
            target_service = ServiceType.AUTRE
            if my_services:
                for s in ServiceType:
                    if s.value == my_services[0] or s.name == my_services[0]:
                        target_service = s
                        break

            t = Ticket(
                uid_public=uid,
                title=request.form.get('title'),
                description=f"[Manuel] {request.form.get('description')}",
                author=current_user,
                solver=current_user,
                target_service=target_service,
                status=TicketStatus.DONE,
                category_ticket="Archive Manuelle",
                created_at=created_at,
                closed_at = get_paris_time(),
                new_user_fullname=request.form.get('user_name')
            )

            db.session.add(t)
            db.session.commit()
            flash(f"Ticket manuel {uid} ajouté à l'historique.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'ajout manuel : {e}", "danger")

        return redirect(url_for('tickets.historique_tickets'))

    # 2. AFFICHAGE DE LA LISTE & RECHERCHE (GET)
    search_query = request.args.get('q', '') # Récupère le texte tapé
    user_role = str(current_user.role.value).upper()
    
    # Base de la requête : Tickets terminés
    query = Ticket.query.filter(Ticket.status == TicketStatus.DONE)

    # Si une recherche est lancée, on ajoute les filtres ILIKE (insensible à la casse)
    if search_query:
        query = query.filter(
            db.or_(
                Ticket.title.ilike(f'%{search_query}%'),
                Ticket.description.ilike(f'%{search_query}%'),
                Ticket.uid_public.ilike(f'%{search_query}%'),
                Ticket.new_user_fullname.ilike(f'%{search_query}%')
            )
        )

    tickets_archives = []

    if 'ADMIN' in user_role:
        tickets_archives = query.order_by(Ticket.created_at.desc()).all()
    else:
        my_services = current_user.get_allowed_services()
        if my_services:
            # On utilise le filtre de recherche déjà appliqué à query
            all_done = query.order_by(Ticket.created_at.desc()).all()
            for t in all_done:
                t_svc = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
                # Sécurité : On n'affiche que ses services, ses tickets créés ou ses tickets résolus
                if (t_svc in my_services) or (t.author_id == current_user.id) or (t.solver_id == current_user.id):
                    tickets_archives.append(t)
        else:
            # Si simple utilisateur, recherche uniquement dans ses propres tickets
            tickets_archives = query.filter(Ticket.author_id == current_user.id).order_by(Ticket.created_at.desc()).all()

    return render_template('tickets/historique_tickets.html', 
                           tickets=tickets_archives, 
                           search_query=search_query)

@tickets_bp.route('/export/history')
@login_required
def export_history():
    try:
        tickets = Ticket.query.filter(Ticket.status == TicketStatus.DONE).all()
        
        data = []
        for t in tickets:
            demandeur = t.new_user_fullname if (t.new_user_fullname and '[Manuel]' in t.description) else t.author.fullname
            
            data.append({
                'Reference': t.uid_public,
                'Date_Creation': t.created_at.strftime('%Y-%m-%d %H:%M'),
                'Date_Cloture': t.closed_at.strftime('%Y-%m-%d %H:%M') if t.closed_at else '',
                'Service_Cible': t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service),
                'Categorie': t.category_ticket,
                'Titre': t.title,
                'Demandeur': demandeur,
                'Resoluteur': t.solver.fullname if t.solver else '',
                'Description': t.description
            })

        df = pd.DataFrame(data)
        
        export_dir = os.path.join(current_app.root_path, 'static', 'uploads')
        os.makedirs(export_dir, exist_ok=True)
        
        filename = f'Historique_Tickets_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        path = os.path.join(export_dir, filename)
        
        df.to_excel(path, index=False)
        
        return send_file(path, as_attachment=True)
        
    except Exception as e:
        flash(f"Erreur lors de l'export : {e}", "danger")
        return redirect(url_for('tickets.historique_tickets'))

@tickets_bp.route('/solver/assign/<int:ticket_id>', methods=['POST'])
@login_required
def assign_ticket(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)
        solver_id = request.form.get('solver_id')
        
        # CAS 1 : "Prendre en charge moi-même" (value="me")
        if solver_id == 'me':
            if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']):
                 flash("Droit insuffisant.", "danger")
                 return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
                 
            # Sécurité Anti-Conflit
            if t.author_id == current_user.id:
               flash("Vous ne pouvez pas traiter votre propre demande.", "warning")
               return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

            t.solver = current_user
            t.status = TicketStatus.IN_PROGRESS
            if not t.assigned_at:
                t.assigned_at = get_paris_time()

            # --- EMAIL ASSIGNATION (AJOUTÉ) ---
            send_assignment_notification(t, current_user)
            send_message_notification(t, f"Votre ticket a été pris en charge par {current_user.fullname}", t.author)
            # ----------------------------------

            flash("Ticket pris en charge.", "success")

        # CAS 2 : Assigner à un autre (nécessite Manager/Directeur/Admin)
        elif solver_id:
            if not check_permission(['MANAGER', 'DIRECTEUR', 'ADMIN']):
                 flash("Action réservée aux managers.", "danger")
                 return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

            u = User.query.get(solver_id)
            if u:
                t.solver = u
                t.status = TicketStatus.IN_PROGRESS
                if not t.assigned_at:
                    t.assigned_at = get_paris_time()
                create_notification(u, f"Ticket {t.uid_public} assigné par {current_user.fullname}.", 'info', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
                
                # --- EMAIL ASSIGNATION (AJOUTÉ) ---
                send_assignment_notification(t, u)
                send_message_notification(t, f"Votre ticket a été assigné à {u.fullname}", t.author)
                # ----------------------------------
                
                flash(f"Assigné à {u.fullname}.", "success")
        
        create_notification(t.author, f"Votre ticket est pris en charge par {t.solver.fullname}.", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
        
        db.session.commit()
        return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))
        
    except Exception as e:
        flash(f"Erreur assignation: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/transfer/<int:ticket_id>', methods=['POST'])
@login_required
def transfer_ticket(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)

    # Même règle que close_ticket : seul le technicien en charge ou un ADMIN.
    if t.solver_id != current_user.id and 'ADMIN' not in safe_role_str(current_user):
        flash("Seul le technicien en charge du ticket peut le transférer.", "danger")
        return redirect(url_for('tickets.solver_dashboard'))

    target_service_name = request.form.get('target_service')
    if not target_service_name:
        return redirect(url_for('tickets.solver_dashboard'))

    try:
        new_service = ServiceType[target_service_name]
    except KeyError:
        flash("Service cible invalide.", "danger")
        return redirect(url_for('tickets.solver_dashboard'))

    old_service_label = t.get_safe_target_service()
    t.target_service = new_service
    t.solver_id = None
    t.status = TicketStatus.PENDING
    db.session.commit()

    # Notifie le nouveau service comme s'il s'agissait d'un nouveau ticket
    # (même mécanisme que new_ticket : email + in-app aux solvers concernés).
    recipients = get_service_emails(new_service)
    if recipients:
        send_service_alert(t, recipients)
    notify_solvers_new_ticket(t)

    flash(f"Ticket {t.uid_public} transféré de {old_service_label} vers {new_service.value}.", "success")
    return redirect(url_for('tickets.solver_dashboard'))
