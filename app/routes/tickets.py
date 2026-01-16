from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, send_file
from flask_login import login_required, current_user
from app.models import Ticket, ServiceType, TicketStatus, UserRole, TicketMessage, Materiel, Pret, Notification, User
from app import db
from datetime import datetime
import json
import os
import socket
import pandas as pd
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps
from app.emails import send_email 

tickets_bp = Blueprint('tickets', __name__)

# --- UTILITAIRES ---
def nocache(view):
    """Décorateur pour empêcher la mise en cache navigateur."""
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0'
        return response
    return no_cache

def create_notification(user, message, category='info', link=None):
    if user:
        n = Notification(user=user, message=message, category=category, link=link)
        db.session.add(n)

def get_hostname_from_ip(ip_address):
    try: return socket.gethostbyaddr(ip_address)[0]
    except: return ip_address

def check_permission(required_roles):
    try:
        current_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
        if 'ADMIN' in current_role: return True
        for req in required_roles:
            if req in current_role: return True
    except Exception as e:
        return False
    return False

# --- ROUTES ---

@tickets_bp.route('/new/<service_name>', methods=['GET', 'POST'])
@login_required
@nocache
def new_ticket(service_name):
    # ... (Code existant inchangé jusqu'au return du POST) ...
    # Je copie le code existant et j'indique où il se termine pour être concis
    # LE CODE EXISTANT DE new_ticket RESTE IDENTIQUE A CELUI QUE TU AS DÉJA
    try:
        service_enum = ServiceType[service_name.upper()]
    except KeyError:
        return redirect(url_for('main.user_portal'))

    user_origins = current_user.get_origin_services()

    if request.method == 'POST':
        category = request.form.get('category_ticket', 'Standard')
        selected_origin = request.form.get('selected_origin')
        if not selected_origin:
            selected_origin = user_origins[0] if user_origins else "INCONNU"
            
        hostname_saisi = request.form.get('hostname')
        final_hostname = hostname_saisi if hostname_saisi else get_hostname_from_ip(request.remote_addr)

        title = request.form.get('title')
        description = request.form.get('description')
        
        if service_name == 'DAF' and category == 'Bon de Commande':
             fournisseur = request.form.get('daf_fournisseur_nom', 'Inconnu')
             title = f"Bon de Commande - {fournisseur}"
             description = request.form.get('description_daf', '')

        role = current_user.role
        if service_enum == ServiceType.INFO and category == "Incident Standard":
            status = TicketStatus.PENDING
        else:
            if role == UserRole.USER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.MANAGER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.DIRECTEUR: status = TicketStatus.VALIDATION_N2
            elif role == UserRole.ADMIN: status = TicketStatus.PENDING
            else: status = TicketStatus.VALIDATION_N1

        today_str = datetime.now().strftime('%Y%m%d')
        base_query = Ticket.query.filter(Ticket.uid_public.like(f"{today_str}%"))
        count = base_query.count()
        
        saved = False
        attempts = 0
        while not saved and attempts < 5:
            attempts += 1
            count += 1
            uid = f"{today_str}-{str(count).zfill(3)}"
            
            daf_lignes = []
            if service_name == 'DAF':
                for i in range(1, 51):
                    des = request.form.get(f'daf_designation_{i}')
                    if des: daf_lignes.append({'designation': des, 'ref': request.form.get(f'daf_ref_{i}'), 'qte': request.form.get(f'daf_qte_{i}'), 'pu': request.form.get(f'daf_pu_{i}'), 'total': request.form.get(f'daf_total_{i}')})
            
            daf_files = []
            daf_rib_filename = None
            
            if request.files and service_name == 'DAF':
                upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', uid)
                os.makedirs(upload_path, exist_ok=True)
                
                for i in range(1, 5):
                    file = request.files.get(f'devis_{i}')
                    if file and file.filename != '':
                        filename = secure_filename(file.filename)
                        file.save(os.path.join(upload_path, filename))
                        daf_files.append(filename)
                
                file_rib = request.files.get('daf_rib')
                if file_rib and file_rib.filename != '':
                    daf_rib_filename = secure_filename(f"RIB_{file_rib.filename}")
                    file_rib.save(os.path.join(upload_path, daf_rib_filename))

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
                service_demandeur=selected_origin,
                tel_demandeur=request.form.get('tel_demandeur'),
                hostname=final_hostname,
                lieu_installation=request.form.get('lieu_installation_user') or request.form.get('lieu_installation_mat'),
                new_user_fullname=f"{request.form.get('new_user_nom')} {request.form.get('new_user_prenom')}",
                new_user_service=request.form.get('new_user_service'),
                new_user_acces=request.form.get('new_user_acces'),
                materiel_list=request.form.get('materiel_list'),
                destinataire_materiel=request.form.get('destinataire_materiel'),
                service_destinataire=request.form.get('service_destinataire'),
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
            
            if request.form.get('new_user_date'):
                try: t.new_user_date = datetime.strptime(request.form.get('new_user_date'), '%Y-%m-%d')
                except: pass
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, send_file
from flask_login import login_required, current_user
from app.models import Ticket, ServiceType, TicketStatus, UserRole, TicketMessage, Materiel, Pret, Notification, User
from app import db
from datetime import datetime
import json
import os
import socket
import pandas as pd
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps

tickets_bp = Blueprint('tickets', __name__)

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
    try:
        service_enum = ServiceType[service_name.upper()]
    except KeyError:
        return redirect(url_for('main.user_portal'))

    user_origins = current_user.get_origin_services()

    if request.method == 'POST':
        category = request.form.get('category_ticket', 'Standard')
        selected_origin = request.form.get('selected_origin')
        if not selected_origin:
            selected_origin = user_origins[0] if user_origins else "INCONNU"
            
        hostname_saisi = request.form.get('hostname')
        final_hostname = hostname_saisi if hostname_saisi else get_hostname_from_ip(request.remote_addr)

        title = request.form.get('title')
        description = request.form.get('description')
        
        if service_name == 'DAF' and category == 'Bon de Commande':
             fournisseur = request.form.get('daf_fournisseur_nom', 'Inconnu')
             title = f"Bon de Commande - {fournisseur}"
             description = request.form.get('description_daf', '')

        role = current_user.role
        
        # --- LOGIQUE DE WORKFLOW (MODIFIÉE) ---
        
        # 1. Workflow Simplifié INFORMATIQUE (Incident / Standard)
        # On saute les validations N1/N2, direct au pool technique.
        if service_enum == ServiceType.INFO and category in ["Standard", "Incident Standard"]:
            status = TicketStatus.PENDING
            
        # 2. Workflow Standard (DAF, Services Généraux, etc.)
        else:
            if role == UserRole.USER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.MANAGER: status = TicketStatus.VALIDATION_N1
            elif role == UserRole.DIRECTEUR: status = TicketStatus.VALIDATION_N2
            elif role == UserRole.ADMIN: status = TicketStatus.PENDING
            else: status = TicketStatus.VALIDATION_N1

        # Génération UID
        today_str = datetime.now().strftime('%Y%m%d')
        base_query = Ticket.query.filter(Ticket.uid_public.like(f"{today_str}%"))
        count = base_query.count() + 1
        uid = f"{today_str}-{str(count).zfill(3)}"
            
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
        
        daf_files = []
        daf_rib_filename = None
        
        if request.files and service_name == 'DAF':
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', uid)
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
        
        if request.form.get('new_user_date'):
            try: t.new_user_date = datetime.strptime(request.form.get('new_user_date'), '%Y-%m-%d')
            except: pass

        try:
            db.session.add(t)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur DB: {e}", "danger")
            return redirect(url_for('main.user_portal'))

        # NOTIFICATIONS AUTOMATIQUES SELON STATUT
        if status == TicketStatus.VALIDATION_N1:
            managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
            for mgr in managers:
                if selected_origin in mgr.get_origin_services():
                    create_notification(mgr, f"Validation requise : {uid}", 'warning', url_for('tickets.manager_dashboard'))
                    
        elif status == TicketStatus.PENDING:
            # Pour l'INFO simplifiée, on notifie directement les techs
            solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
            for s in solvers:
                 if s.role == UserRole.ADMIN or service_name in s.get_allowed_services():
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
        
        can_view = False
        if 'ADMIN' in user_role: can_view = True
        elif ticket.author_id == current_user.id: can_view = True
        elif 'SOLVER' in user_role and target_svc in current_user.get_allowed_services(): can_view = True
        elif 'MANAGER' in user_role or 'DIRECTEUR' in user_role:
            if ticket.service_demandeur in current_user.get_origin_services(): can_view = True
            if target_svc in current_user.get_allowed_services(): can_view = True
        
        if not can_view:
            flash("Accès non autorisé à ce ticket.", "warning")
            return redirect(url_for('main.user_portal'))

        if request.method == 'POST' and request.form.get('message'):
            msg = TicketMessage(content=request.form.get('message'), ticket=ticket, author=current_user)
            db.session.add(msg)
            db.session.commit()
            return redirect(url_for('tickets.view_ticket', ticket_uid=ticket_uid))
            
        return render_template('tickets/detail.html', ticket=ticket)

    except Exception as e:
        print(f"ERREUR VIEW TICKET: {e}")
        flash(f"Erreur d'affichage : {str(e)}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/manager/dashboard')
@login_required
@nocache
def manager_dashboard():
    try:
        if not check_permission(['MANAGER', 'DIRECTEUR', 'ADMIN']):
            if 'SOLVER' in safe_role_str(current_user): return redirect(url_for('tickets.solver_dashboard'))
            return render_template('errors/catdance.html'), 403
        
        my_origins = current_user.get_origin_services() 
        my_targets = current_user.get_allowed_services()
        
        tickets_n1 = []
        if my_origins: 
            tickets_n1 = Ticket.query.filter(
                Ticket.status == TicketStatus.VALIDATION_N1,
                Ticket.service_demandeur.in_(my_origins),
                Ticket.author_id != current_user.id
            ).all()

        tickets_n2 = []
        if my_targets:
            base_query = Ticket.query.filter(Ticket.target_service.in_(my_targets))
            if 'DAF' in my_targets:
                if current_user.role == UserRole.DIRECTEUR:
                    candidates = base_query.filter(Ticket.status.in_([TicketStatus.VALIDATION_N2, TicketStatus.DAF_SIGNATURE])).all()
                else:
                    candidates = base_query.filter(Ticket.status == TicketStatus.VALIDATION_N2).all()
            else:
                candidates = base_query.filter(Ticket.status == TicketStatus.VALIDATION_N2).all()
            tickets_n2 = candidates

        return render_template('tickets/manager_dashboard.html', tickets_n1=tickets_n1, tickets_n2=tickets_n2)
    except Exception as e:
        flash(f"Erreur Dashboard: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/take/<int:ticket_id>')
@login_required
def take_ticket(ticket_id):
    try:
        if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): 
            flash("Droits insuffisants.", "danger")
            return redirect(url_for('main.user_portal'))
            
        t = Ticket.query.get_or_404(ticket_id)
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
                t.status = TicketStatus.VALIDATION_N2
                db.session.commit()
                flash("Bon transmis au Manager.", "success")
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
                t.closed_at = datetime.now()
                db.session.commit()
                flash("Bon signé. Ticket clôturé.", "success")
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/solver/close/<int:ticket_id>')
@login_required
def close_ticket(ticket_id):
    try:
        t = Ticket.query.get_or_404(ticket_id)
        t.status = TicketStatus.DONE
        t.closed_at = datetime.now()
        db.session.commit()
        return redirect(url_for('tickets.solver_dashboard'))
    except Exception as e:
        flash(f"Erreur fermeture: {e}", "danger")
        return redirect(url_for('main.user_portal'))

@tickets_bp.route('/manager/action/<int:ticket_id>/<action>')
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
        elif action == 'refuse':
            if t.target_service == ServiceType.DAF and t.status in [TicketStatus.VALIDATION_N2, TicketStatus.DAF_SIGNATURE]:
                t.status = TicketStatus.IN_PROGRESS
            else:
                t.status = TicketStatus.REFUSED
        db.session.commit()
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur action: {e}", "danger")
        return redirect(url_for('tickets.manager_dashboard'))
        
@tickets_bp.route('/solver/dashboard')
@login_required
@nocache
def solver_dashboard():
    try:
        if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']):
            return render_template('errors/catdance.html'), 403

        my_targets = current_user.get_allowed_services() 
        user_role = safe_role_str(current_user)
        
        if user_role in ['MANAGER', 'DIRECTEUR'] and not my_targets:
             flash("Aucun service technique assigné.", "warning")
             return redirect(url_for('tickets.manager_dashboard'))

        query = Ticket.query.filter(Ticket.status != TicketStatus.DONE)
        
        if 'ADMIN' not in user_role and my_targets:
            tickets_all = query.all()
            tickets_pool = [t for t in tickets_all if t.get_safe_target_service() in my_targets]
        else:
            tickets_pool = query.all()

        pending_tickets = [t for t in tickets_pool if t.solver_id is None and t.get_safe_status() == 'EN_ATTENTE_TRAITEMENT']
        
        pool_standard = [t for t in pending_tickets if not t.category_ticket or t.category_ticket in ['Standard', 'Incident Standard']]
        pool_users = [t for t in pending_tickets if t.category_ticket == 'Nouvel Utilisateur']
        pool_materiel = [t for t in pending_tickets if t.category_ticket == 'Matériel']
        pool_bons = [t for t in pending_tickets if t.category_ticket == 'Bon de Commande']
        
        mine = Ticket.query.filter_by(solver_id=current_user.id, status=TicketStatus.IN_PROGRESS).all()
        
        hist_query = Ticket.query.filter_by(status=TicketStatus.DONE)
        history_all = hist_query.order_by(Ticket.closed_at.desc()).limit(20).all()
        if 'ADMIN' not in user_role and my_targets:
            history = [t for t in history_all if t.get_safe_target_service() in my_targets]
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

        return render_template('tickets/service_dashboard.html', stats=stats, pool_standard=pool_standard, pool_users=pool_users, pool_materiel=pool_materiel, pool_bons=pool_bons, mine=mine, history=history, solvers=team_solvers, services=ServiceType)
    except Exception as e:
        return render_template('base.html', content=f"<h1>Erreur 500 Dashboard</h1><p>{e}</p>")
        
@tickets_bp.route('/historique', methods=['GET', 'POST'])
@login_required
@nocache
def historique_tickets():
    return render_template('tickets/historique_tickets.html', tickets=[]) 

@tickets_bp.route('/export/history')
@login_required
def export_history():
    return redirect(url_for('tickets.solver_dashboard')) 

@tickets_bp.route('/solver/assign/<int:ticket_id>', methods=['POST'])
@login_required
def assign_ticket(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    sid = request.form.get('solver_id')
    if sid:
        u = User.query.get(sid)
        if u:
            t.solver = u
            t.status = TicketStatus.IN_PROGRESS
            db.session.commit()
    return redirect(url_for('tickets.solver_dashboard'))

@tickets_bp.route('/solver/transfer/<int:ticket_id>', methods=['POST'])
@login_required
def transfer_ticket(ticket_id):
    return redirect(url_for('tickets.solver_dashboard'))
