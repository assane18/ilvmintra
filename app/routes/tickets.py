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

            try:
                db.session.add(t)
                db.session.commit()
                saved = True
            except IntegrityError:
                db.session.rollback()
                continue

        link_mgr = url_for('tickets.manager_dashboard')
        if status == TicketStatus.VALIDATION_N1:
            managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
            for mgr in managers:
                if selected_origin in mgr.get_origin_services():
                    create_notification(mgr, f"Validation DA : {uid} ({selected_origin})", 'warning', link_mgr)
                    
        elif status == TicketStatus.VALIDATION_N2:
            target_managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
            for tm in target_managers:
                if service_name in tm.get_allowed_services(): 
                    create_notification(tm, f"Validation N2 : {uid}", 'warning', link_mgr)

        elif status == TicketStatus.PENDING:
            solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
            for solver in solvers:
                 if solver.role == UserRole.ADMIN or service_name in solver.get_allowed_services():
                    create_notification(solver, f"Nouveau ticket : {uid}", 'info', url_for('tickets.solver_dashboard'))

        flash(f'Demande {uid} enregistrée.', 'success')
        return redirect(url_for('main.user_portal'))

    return render_template('tickets/new_ticket.html', service=service_enum, service_name=service_name, user_origins=user_origins)

@tickets_bp.route('/manager/dashboard')
@login_required
@nocache
def manager_dashboard():
    try:
        if not check_permission(['MANAGER', 'DIRECTEUR', 'ADMIN']):
            if 'SOLVER' in str(current_user.role).upper(): return redirect(url_for('tickets.solver_dashboard'))
            return render_template('errors/catdance.html'), 403
        
        my_origins = current_user.get_origin_services() # GU
        my_targets = current_user.get_allowed_services() # GS
        
        tickets_n1 = []
        if my_origins: 
            tickets_n1 = Ticket.query.filter(
                Ticket.status == TicketStatus.VALIDATION_N1,
                Ticket.service_demandeur.in_(my_origins),
                Ticket.author_id != current_user.id
            ).all()

        tickets_n2 = []
        if my_targets:
            # Pour le workflow standard : N2
            # Pour le workflow DAF : N2 (Manager) ET DAF_SIGNATURE (Directeur)
            
            # Récupération de base
            base_query = Ticket.query.filter(Ticket.target_service.in_(my_targets))
            
            # Si c'est un DAF
            if 'DAF' in my_targets:
                if current_user.role == UserRole.DIRECTEUR:
                    # Le directeur DAF voit les signatures
                    candidates = base_query.filter(Ticket.status.in_([TicketStatus.VALIDATION_N2, TicketStatus.DAF_SIGNATURE])).all()
                else:
                    # Le manager voit les validations
                    candidates = base_query.filter(Ticket.status == TicketStatus.VALIDATION_N2).all()
            else:
                # Standard
                candidates = base_query.filter(Ticket.status == TicketStatus.VALIDATION_N2).all()
                
            tickets_n2 = candidates

        return render_template('tickets/manager_dashboard.html', tickets_n1=tickets_n1, tickets_n2=tickets_n2)
    except Exception as e:
        print(f"ERREUR MANAGER DASHBOARD: {e}")
        return render_template('base.html', content=f"<h1>Erreur 500</h1><p>{e}</p>")

@tickets_bp.route('/manager/action/<int:ticket_id>/<action>')
@login_required
def manager_action(ticket_id, action):
    try:
        if not check_permission(['MANAGER', 'DIRECTEUR', 'ADMIN']): return render_template('errors/catdance.html'), 403
        t = Ticket.query.get_or_404(ticket_id)
        
        if action == 'validate':
            # --- LOGIQUE DE VALIDATION ---
            
            if t.status == TicketStatus.VALIDATION_N1:
                # Validation du DA (Directeur Service Demandeur)
                if t.target_service == ServiceType.DAF:
                    # WORKFLOW DAF : On saute directement au Pool (Pending) pour que le Solver prépare
                    t.status = TicketStatus.PENDING
                    flash(f"Validation DA effectuée. Dossier transmis à la DAF pour traitement.", "success")
                    # Notif aux solvers DAF
                    solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
                    for s in solvers:
                        if s.role == UserRole.ADMIN or 'DAF' in s.get_allowed_services():
                            create_notification(s, f"DAF à traiter : {t.uid_public}", 'info', url_for('tickets.solver_dashboard'))
                else:
                    # WORKFLOW STANDARD : On passe à N2
                    t.status = TicketStatus.VALIDATION_N2
                    flash(f"Ticket {t.uid_public} validé N1. Transmis pour validation technique.", "success")
                    target_managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
                    for tm in target_managers:
                        if t.target_service.value in tm.get_allowed_services():
                            create_notification(tm, f"Validation N2 : {t.uid_public}", 'warning', url_for('tickets.manager_dashboard'))
            
            elif t.status == TicketStatus.VALIDATION_N2:
                # Validation Technique (GS)
                if t.target_service == ServiceType.DAF:
                    # WORKFLOW DAF : Manager valide -> Passe à Signature Directeur
                    t.status = TicketStatus.DAF_SIGNATURE
                    flash(f"Dossier {t.uid_public} validé. Transmis au Directeur pour signature.", "success")
                    # Notif Directeur DAF
                    directeurs = User.query.filter(User.role == UserRole.DIRECTEUR).all()
                    for d in directeurs:
                        if 'DAF' in d.get_allowed_services():
                            create_notification(d, f"Signature requise : {t.uid_public}", 'important', url_for('tickets.manager_dashboard'))
                else:
                    # WORKFLOW STANDARD : Validé -> Pool
                    t.status = TicketStatus.PENDING
                    flash(f"Ticket {t.uid_public} validé N2. En attente de technicien.", "success")
                    solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
                    for s in solvers:
                        if s.role == UserRole.ADMIN or t.target_service.value in s.get_allowed_services():
                            create_notification(s, f"Nouveau ticket : {t.uid_public}", 'info', url_for('tickets.solver_dashboard'))

        elif action == 'refuse':
            # --- LOGIQUE DE REFUS ---
            if t.target_service == ServiceType.DAF and t.status in [TicketStatus.VALIDATION_N2, TicketStatus.DAF_SIGNATURE]:
                # Si DAF refuse en interne -> Retour au Solver
                t.status = TicketStatus.IN_PROGRESS
                flash(f"Dossier refusé. Retourné au gestionnaire pour correction.", "warning")
                if t.solver:
                    create_notification(t.solver, f"Dossier {t.uid_public} refusé par Manager/Dir.", 'danger', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
            else:
                # Refus standard -> Annulation
                t.status = TicketStatus.REFUSED
                flash(f"Ticket {t.uid_public} refusé.", "danger")
                create_notification(t.author, f"Ticket {t.uid_public} refusé.", 'danger', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
            
        db.session.commit()
        return redirect(url_for('tickets.manager_dashboard'))
    except Exception as e:
        flash(f"Erreur action: {e}", "danger")
        return redirect(url_for('tickets.manager_dashboard'))

# --- NOUVELLES ROUTES DAF WORKFLOW ---

@tickets_bp.route('/solver/daf_submit/<int:ticket_id>', methods=['POST'])
@login_required
def daf_solver_submit(ticket_id):
    """Le solver DAF uploade le bon préparé et soumet au Manager."""
    t = Ticket.query.get_or_404(ticket_id)
    if not check_permission(['SOLVER', 'ADMIN']) or t.target_service != ServiceType.DAF:
        return render_template('errors/catdance.html'), 403

    if 'daf_prepared_file' in request.files:
        file = request.files['daf_prepared_file']
        if file and file.filename != '':
            filename = secure_filename(f"PREPA_{t.uid_public}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', t.uid_public)
            os.makedirs(upload_path, exist_ok=True)
            file.save(os.path.join(upload_path, filename))
            
            t.daf_solver_file = filename
            t.status = TicketStatus.VALIDATION_N2 # Envoi au Manager DAF
            
            flash("Bon de commande préparé transmis au Manager.", "success")
            
            # Notif Managers DAF
            managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR])).all()
            for m in managers:
                if 'DAF' in m.get_allowed_services():
                    create_notification(m, f"Validation requise : {t.uid_public}", 'warning', url_for('tickets.manager_dashboard'))
            
            db.session.commit()
    else:
        flash("Veuillez joindre le fichier préparé.", "danger")
    
    return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

@tickets_bp.route('/director/daf_sign/<int:ticket_id>', methods=['POST'])
@login_required
def daf_director_sign(ticket_id):
    """Le directeur DAF uploade le bon signé et clôture."""
    t = Ticket.query.get_or_404(ticket_id)
    if not check_permission(['DIRECTEUR', 'ADMIN']) or t.target_service != ServiceType.DAF:
        return render_template('errors/catdance.html'), 403

    if 'daf_signed_file' in request.files:
        file = request.files['daf_signed_file']
        if file and file.filename != '':
            filename = secure_filename(f"SIGNE_{t.uid_public}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', t.uid_public)
            os.makedirs(upload_path, exist_ok=True)
            file.save(os.path.join(upload_path, filename))
            
            t.daf_signed_file = filename
            t.status = TicketStatus.DONE # Clôture finale
            t.closed_at = datetime.now()
            
            flash("Bon de commande signé et validé. Ticket clôturé.", "success")
            
            # Notif Solver et Auteur
            if t.solver:
                create_notification(t.solver, f"Bon {t.uid_public} signé par le Directeur.", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
            create_notification(t.author, f"Votre demande {t.uid_public} est terminée (Bon signé).", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
            
            db.session.commit()
    else:
        flash("Veuillez joindre le document signé.", "danger")
    
    return redirect(url_for('tickets.manager_dashboard'))


# --- ROUTES STANDARD EXISTANTES ---

@tickets_bp.route('/solver/dashboard')
@login_required
@nocache
def solver_dashboard():
    # ... (Code existant inchangé) ...
    # Je ne remets pas tout le code pour économiser l'espace, il reste identique
    # Juste s'assurer que PENDING est bien traité
    try:
        if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']):
            return render_template('errors/catdance.html'), 403

        my_targets = current_user.get_allowed_services() 
        user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
        
        if user_role in ['MANAGER', 'DIRECTEUR'] and not my_targets:
             flash("Aucun service technique assigné à votre compte.", "warning")
             return redirect(url_for('tickets.manager_dashboard'))

        query = Ticket.query.filter(Ticket.status != TicketStatus.DONE)
        
        if 'ADMIN' not in user_role and my_targets:
            tickets_all = query.all()
            tickets_pool = [t for t in tickets_all if t.target_service.value in my_targets]
        else:
            tickets_pool = query.all()

        pending_tickets = [t for t in tickets_pool if t.solver_id is None and t.status == TicketStatus.PENDING]
        pool_standard = [t for t in pending_tickets if not t.category_ticket or t.category_ticket in ['Standard', 'Incident Standard']]
        pool_users = [t for t in pending_tickets if t.category_ticket == 'Nouvel Utilisateur']
        pool_materiel = [t for t in pending_tickets if t.category_ticket == 'Matériel']
        pool_bons = [t for t in pending_tickets if t.category_ticket == 'Bon de Commande']
        
        mine = Ticket.query.filter_by(solver_id=current_user.id, status=TicketStatus.IN_PROGRESS).all()
        
        hist_query = Ticket.query.filter_by(status=TicketStatus.DONE)
        history_all = hist_query.order_by(Ticket.closed_at.desc()).limit(20).all()
        if 'ADMIN' not in user_role and my_targets:
            history = [t for t in history_all if t.target_service.value in my_targets]
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
        print(f"ERREUR SOLVER DASHBOARD: {e}")
        return render_template('base.html', content=f"<h1>Erreur 500</h1><p>{e}</p>")

@tickets_bp.route('/view/<string:ticket_uid>', methods=['GET', 'POST'])
@login_required
@nocache
def view_ticket(ticket_uid):
    ticket = Ticket.query.filter_by(uid_public=ticket_uid).first_or_404()
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    
    can_view = False
    if 'ADMIN' in user_role: can_view = True
    elif ticket.author_id == current_user.id: can_view = True
    elif 'SOLVER' in user_role and ticket.target_service.value in current_user.get_allowed_services(): can_view = True
    elif 'MANAGER' in user_role or 'DIRECTEUR' in user_role:
        if ticket.service_demandeur in current_user.get_origin_services(): can_view = True
        if ticket.target_service.value in current_user.get_allowed_services(): can_view = True
    
    if not can_view: return render_template('errors/catdance.html'), 403

    if request.method == 'POST' and request.form.get('message'):
        msg = TicketMessage(content=request.form.get('message'), ticket=ticket, author=current_user)
        db.session.add(msg)
        if current_user.id == ticket.author_id:
            if ticket.solver: create_notification(ticket.solver, f"Message sur {ticket.uid_public}", 'info', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
        else:
            create_notification(ticket.author, f"Réponse support sur {ticket.uid_public}", 'info', url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
        db.session.commit()
        return redirect(url_for('tickets.view_ticket', ticket_uid=ticket_uid))
    return render_template('tickets/detail.html', ticket=ticket)

@tickets_bp.route('/solver/take/<int:ticket_id>')
@login_required
def take_ticket(ticket_id):
    if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): return render_template('errors/catdance.html'), 403
    t = Ticket.query.get_or_404(ticket_id)
    t.solver = current_user
    t.status = TicketStatus.IN_PROGRESS
    create_notification(t.author, f"Pris en charge par {current_user.fullname}", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
    db.session.commit()
    return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public))

@tickets_bp.route('/solver/close/<int:ticket_id>')
@login_required
def close_ticket(ticket_id):
    if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): return render_template('errors/catdance.html'), 403
    t = Ticket.query.get_or_404(ticket_id)
    t.status = TicketStatus.DONE
    t.closed_at = datetime.now()
    create_notification(t.author, f"Ticket {t.uid_public} résolu.", 'success', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
    db.session.commit()
    return redirect(url_for('tickets.solver_dashboard'))

@tickets_bp.route('/historique', methods=['GET', 'POST'])
@login_required
@nocache
def historique_tickets():
    my_targets = current_user.get_allowed_services()
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()

    if request.method == 'POST':
        title = request.form.get('title')
        user_name = request.form.get('user_name') # Nom du demandeur manuel
        description = request.form.get('description')
        date_creation = request.form.get('date_creation')
        d_create = datetime.now()
        if date_creation:
            try: d_create = datetime.strptime(date_creation, '%Y-%m-%dT%H:%M')
            except: pass
        
        day_str = d_create.strftime('%Y%m%d')
        base_query = Ticket.query.filter(Ticket.uid_public.like(f"{day_str}%"))
        count = base_query.count() + 1
        uid = f"{day_str}-{str(count).zfill(3)}"
        
        target_svc = ServiceType.INFO
        if my_targets:
            try: target_svc = ServiceType[my_targets[0]]
            except: pass

        t = Ticket(
            title=title, 
            description=f"Ticket manuel ajouté.\n\n{description}", 
            author=current_user, 
            new_user_fullname=user_name,
            target_service=target_svc, 
            status=TicketStatus.DONE, 
            uid_public=uid, 
            created_at=d_create, 
            closed_at=datetime.now(), 
            solver=current_user
        )
        db.session.add(t)
        db.session.commit()
        return redirect(url_for('tickets.historique_tickets'))

    if 'ADMIN' not in user_role and my_targets:
        tickets_all = Ticket.query.filter_by(status=TicketStatus.DONE).order_by(Ticket.closed_at.desc()).all()
        tickets = [t for t in tickets_all if t.target_service.value in my_targets]
    else:
        tickets = Ticket.query.filter_by(status=TicketStatus.DONE).order_by(Ticket.closed_at.desc()).all()
    return render_template('tickets/historique_tickets.html', tickets=tickets)

@tickets_bp.route('/export/history')
@login_required
def export_history():
    if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): return render_template('errors/catdance.html'), 403
    
    my_targets = current_user.get_allowed_services()
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    
    query = Ticket.query.filter_by(status=TicketStatus.DONE).order_by(Ticket.closed_at.desc())
    all_tickets = query.all()
    
    if 'ADMIN' not in user_role and my_targets:
        tickets = [t for t in all_tickets if t.target_service.value in my_targets]
    else:
        tickets = all_tickets
        
    data = []
    for t in tickets:
        demandeur = t.new_user_fullname if t.new_user_fullname else t.author.fullname
        data.append({
            'ID': t.uid_public,
            'Date Création': t.created_at.strftime('%d/%m/%Y %H:%M'),
            'Date Clôture': t.closed_at.strftime('%d/%m/%Y %H:%M') if t.closed_at else '',
            'Titre': t.title,
            'Demandeur': demandeur,
            'Service Demandeur': t.service_demandeur,
            'Service Cible': t.target_service.value,
            'Technicien': t.solver.fullname if t.solver else 'Aucun',
            'Description': t.description
        })
        
    df = pd.DataFrame(data)
    export_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(export_dir, exist_ok=True)
    filename = f'Historique_Tickets_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    path = os.path.join(export_dir, filename)
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

@tickets_bp.route('/solver/assign/<int:ticket_id>', methods=['POST'])
@login_required
def assign_ticket(ticket_id):
    if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): return render_template('errors/catdance.html'), 403
    t = Ticket.query.get_or_404(ticket_id)
    sid = request.form.get('solver_id')
    if sid:
        u = User.query.get(sid)
        if u:
            t.solver = u
            t.status = TicketStatus.IN_PROGRESS
            create_notification(u, f"Ticket {t.uid_public} assigné", 'warning', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
            db.session.commit()
    return redirect(url_for('tickets.solver_dashboard'))

@tickets_bp.route('/solver/transfer/<int:ticket_id>', methods=['POST'])
@login_required
def transfer_ticket(ticket_id):
    if not check_permission(['SOLVER', 'ADMIN', 'MANAGER', 'DIRECTEUR']): return render_template('errors/catdance.html'), 403
    t = Ticket.query.get_or_404(ticket_id)
    ns = request.form.get('target_service')
    try:
        t.target_service = ServiceType[ns]
        t.solver = None
        t.status = TicketStatus.PENDING
        db.session.commit()
        flash(f"Transféré vers {ns}", "success")
    except:
        flash("Erreur transfert", "danger")
    return redirect(url_for('tickets.solver_dashboard'))
