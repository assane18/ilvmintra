from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, send_file
from flask_login import login_required, current_user
from app.models import Ticket, ServiceType, TicketStatus, UserRole, TicketMessage, Materiel, Pret, Notification, User, Recruitment, RecruitmentStatus
from app import db
from datetime import datetime
import pytz
import json
import os
import socket
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

# --- ROUTES ---

@tickets_bp.route('/new/<service_name>', methods=['GET', 'POST'])
@login_required
@nocache
def new_ticket(service_name):
    
    # --- 1. SÉCURITÉ SPÉCIFIQUE MATÉRIEL ---
    if service_name.upper() == 'MATERIEL':
        role = str(current_user.role.value).upper()
        if 'MANAGER' not in role and 'DIRECTEUR' not in role and 'ADMIN' not in role:
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
        
        if service_name == 'DAF' and category == 'Bon de Commande':
             fournisseur = request.form.get('daf_fournisseur_nom', 'Inconnu')
             title = f"Bon de Commande - {fournisseur}"
             description = request.form.get('description_daf', '')
        
        if service_name == 'IMAGO':
            category = 'Dépannage Imago'

        selected_origin = request.form.get('selected_origin')
        if not selected_origin:
            selected_origin = user_origins[0] if user_origins else "INCONNU"
            
        hostname_saisi = request.form.get('hostname')
        final_hostname = hostname_saisi if hostname_saisi else get_hostname_from_ip(request.remote_addr)

        role = current_user.role
        
        # --- WORKFLOW ---
        status = TicketStatus.VALIDATION_N1 

        if (service_enum == ServiceType.INFO and category in ["Standard", "Incident Standard"]) or (service_enum == ServiceType.IMAGO):
            status = TicketStatus.PENDING
        
        elif service_name == 'DRH':
            status = TicketStatus.PENDING

        elif service_name.upper() == 'MATERIEL':
            status = TicketStatus.VALIDATION_N2 

        else:
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
            
        # DAF Lignes
        daf_lignes = []
        if service_name == 'DAF':
            for i in range(1, 51):
                des = request.form.get(f'daf_designation_{i}')
                if des: daf_lignes.append({
                    'designation': des, 
                    'ref': request.form.get(f'daf_ref_{i}'), 
                    'qte': request.form.get(f'daf_qte_{i}'), 
                    'pu': request.form.get(f'daf_pu_{i}'), 
                    'total': request.form.get(f'daf_total_{i}')
                })
        
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
                    
        elif status == TicketStatus.VALIDATION_N2 and service_name.upper() == 'MATERIEL':
             targets = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
             for u in targets:
                 if 'INFORMATIQUE' in u.get_allowed_services() or 'INFO' in u.get_allowed_services():
                     create_notification(u, f"Demande Matériel à valider : {uid}", 'warning', url_for('tickets.manager_dashboard'))

        elif status == TicketStatus.PENDING:
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

        flash(f'Demande {uid} enregistrée.', 'success')
        return redirect(url_for('main.user_portal'))

    return render_template('tickets/new_ticket.html', service=service_enum, service_name=service_name, user_origins=user_origins)

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
            if ticket.solver and current_user.id != ticket.solver_id:
                create_notification(ticket.solver, f"Message sur {ticket.uid_public}", 'warning', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
            if ticket.author and current_user.id != ticket.author_id:
                create_notification(ticket.author, f"Réponse sur {ticket.uid_public}", 'success', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
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
    is_rh = 'DRH' in current_user.get_allowed_services()
    if not (('SOLVER' in role and is_rh) or 'ADMIN' in role):
         flash("Action réservée aux Solvers RH.", "danger")
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

        return render_template('tickets/manager_dashboard.html', 
                            tickets_n1=tickets_n1, 
                            tickets_n2=tickets_n2, 
                            fcpi_requests=fcpi_requests)

    except Exception as e:
        flash(f"Erreur Dashboard: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/manager/action/<int:ticket_id>/<action>', methods=['GET', 'POST'])
@login_required
def manager_action(ticket_id, action):
    try:
        t = Ticket.query.get_or_404(ticket_id)
        
        if action == 'validate':
            if t.status == TicketStatus.VALIDATION_N1:
                if t.target_service == ServiceType.DAF: t.status = TicketStatus.PENDING
                else: t.status = TicketStatus.VALIDATION_N2
                
            elif t.status == TicketStatus.VALIDATION_N2:
                if t.target_service == ServiceType.DAF: t.status = TicketStatus.DAF_SIGNATURE
                else: t.status = TicketStatus.PENDING
                
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
        create_notification(t.author, f"Pris en charge par {current_user.fullname}", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
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
                
                db.session.commit()
                flash("Bon signé. Ticket clôturé.", "success")
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/close/<int:ticket_id>', methods=['POST'])
@login_required
def close_ticket(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)
        t.status = TicketStatus.DONE
        t.closed_at = get_paris_time()
        
        # --- NOTIFICATION CLOTURE ---
        create_notification(
            user=t.author,
            message=f"Votre ticket {t.uid_public} a été traité et clôturé.",
            category='success',
            link=url_for('tickets.view_ticket', ticket_uid=t.uid_public)
        )

        db.session.commit()
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

        pool_imago = [t for t in pending_tickets if str(t.target_service) == 'IMAGO' or t.target_service == ServiceType.IMAGO]
        
        pool_standard = [
            t for t in pending_tickets 
            if (not t.category_ticket or t.category_ticket in ['Standard', 'Incident Standard', 'Demande RH']) 
            and str(t.target_service) != 'IMAGO' and t.target_service != ServiceType.IMAGO
            and t.target_service != drh_enum 
        ]
        
        pool_users = [t for t in pending_tickets if t.category_ticket == 'Nouvel Utilisateur']
        pool_materiel = [t for t in pending_tickets if t.category_ticket == 'Matériel' or t.category_ticket == 'Demande Matériel']
        pool_bons = [t for t in pending_tickets if t.category_ticket == 'Bon de Commande']
        
        pool_drh = [t for t in pending_tickets if t.target_service == drh_enum or str(t.target_service) == 'DRH' or str(t.target_service) == 'GS-DRH']
        
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

    # 2. AFFICHAGE DE LA LISTE (GET)
    user_role = str(current_user.role.value).upper()
    query = Ticket.query.filter(Ticket.status == TicketStatus.DONE)
    
    tickets_archives = []
    
    if 'ADMIN' in user_role:
        tickets_archives = query.order_by(Ticket.created_at.desc()).all()
    else:
        my_services = current_user.get_allowed_services()
        if my_services:
            all_done = query.order_by(Ticket.created_at.desc()).all()
            for t in all_done:
                t_svc = t.target_service.value if hasattr(t.target_service, 'value') else str(t.target_service)
                if (t_svc in my_services) or (t.author_id == current_user.id) or (t.solver_id == current_user.id):
                    tickets_archives.append(t)
        else:
             tickets_archives = query.filter(Ticket.author_id == current_user.id).order_by(Ticket.created_at.desc()).all()

    return render_template('tickets/historique_tickets.html', tickets=tickets_archives)

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
                create_notification(u, f"Ticket {t.uid_public} assigné par {current_user.fullname}.", 'info', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
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
    return redirect(url_for('tickets.solver_dashboard'))
