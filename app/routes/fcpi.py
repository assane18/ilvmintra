from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_file, jsonify
from flask_login import login_required, current_user
from app.models import Recruitment, RecruitmentStatus, User, ServiceType, Ticket, TicketStatus, UserRole, Notification
from app import db
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import json
import shutil 

fcpi_bp = Blueprint('fcpi', __name__)

# --- FONCTION UTILITAIRE DE CRÉATION DE TICKET (Vers. Robuste & Complète) ---
def create_sub_ticket(recruitment, target_service, title, description, specific_fields=None, files_to_copy=None, custom_suffix=None):
    """
    Crée un ticket enfant avec transfert de données et fichiers.
    Basé sur la structure stable de fcpi (2).py mais avec les fonctionnalités avancées.
    """
    
    # 1. Génération Suffixe & UID
    if custom_suffix:
        suffix = custom_suffix
    else:
        # Fallback : 3 premières lettres du service
        try:
            val = target_service.value if hasattr(target_service, 'value') else str(target_service)
            suffix = val[:3].upper()
        except:
            suffix = "AUT"
            
    uid = f"{recruitment.uid_public}-{suffix}"
    full_title = f"[FCPI] {title} - {recruitment.nom_agent} {recruitment.prenom_agent}"

    # 2. Création Objet Ticket
    t = Ticket(
        uid_public=uid,
        title=full_title,
        description=description,
        author_id=recruitment.author_id, # Utilisation ID direct pour stabilité
        target_service=target_service,
        status=TicketStatus.PENDING, 
        category_ticket="Nouvel Utilisateur",
        service_demandeur=recruitment.service_agent,
        
        # Champs spécifiques FCPI
        new_user_fullname=f"{recruitment.nom_agent} {recruitment.prenom_agent}",
        new_user_service=recruitment.service_agent,
        new_user_date=recruitment.date_entree,
        created_at=datetime.utcnow()
    )

    # 3. Remplissage champs dynamiques (Matériel, Accès...)
    if specific_fields:
        if 'materiel_list' in specific_fields: t.materiel_list = specific_fields['materiel_list']
        if 'new_user_acces' in specific_fields: t.new_user_acces = specific_fields['new_user_acces']
        if 'lieu_installation' in specific_fields: t.lieu_installation = specific_fields['lieu_installation']
        if 'destinataire_materiel' in specific_fields: t.destinataire_materiel = specific_fields['destinataire_materiel']

    # 4. Copie physique des fichiers (Le point critique)
    ticket_files = []
    if files_to_copy:
        src_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'fcpi', recruitment.uid_public)
        dest_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', uid)
        
        if os.path.exists(src_dir):
            os.makedirs(dest_dir, exist_ok=True)
            for filename in files_to_copy:
                if filename:
                    src_file = os.path.join(src_dir, filename)
                    if os.path.exists(src_file):
                        try:
                            shutil.copy2(src_file, dest_dir)
                            ticket_files.append(filename)
                        except Exception as e:
                            print(f"Erreur copie fichier {filename}: {e}")
    
    if ticket_files:
        t.daf_files_json = json.dumps(ticket_files)

    db.session.add(t)
    db.session.flush() # Important: Flush sans commit pour l'ID
    
    # 5. Notification (Inline pour éviter problèmes d'import)
    try:
        solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
        for s in solvers:
            allowed = s.get_allowed_services()
            svc_val = target_service.value if hasattr(target_service, 'value') else str(target_service)
            svc_name = target_service.name if hasattr(target_service, 'name') else str(target_service)
            
            should_notify = False
            if 'ADMIN' in str(s.role): should_notify = True
            else:
                for a in allowed:
                    if str(a) == svc_val or str(a) == svc_name:
                        should_notify = True
                        break
            
            if should_notify:
                n = Notification(user=s, message=f"Nouvelle Arrivée : {full_title}", category='info', link=url_for('tickets.view_ticket', ticket_uid=uid))
                db.session.add(n)
    except: pass
            
    return t.id

# --- ROUTES ---

@fcpi_bp.route('/fcpi/check_access')
@login_required
def check_access():
    """
    Route hybride : JSON pour l'API, Redirection pour le clic utilisateur.
    """
    role = str(current_user.role.value).upper()
    has_access = 'MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role

    # Si c'est le navigateur qui demande (clic sur le lien), on redirige vers le formulaire
    if not request.is_json and 'text/html' in request.accept_mimetypes:
        if has_access:
            return redirect(url_for('fcpi.new_fcpi'))
        else:
            flash("Accès réservé aux Managers.", "warning")
            return redirect(url_for('main.user_portal'))

    return jsonify({'access': has_access})

@fcpi_bp.route('/fcpi/new', methods=['GET', 'POST'])
@login_required
def new_fcpi():
    """
    Route de création. Utilise explicitement /fcpi/new pour correspondre à votre attente.
    """
    role = str(current_user.role.value).upper()
    if 'MANAGER' not in role and 'DIRECTEUR' not in role and 'ADMIN' not in role:
        flash("Accès réservé.", "warning")
        return redirect(url_for('main.user_portal'))

    if request.method == 'POST':
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            count = Recruitment.query.filter(Recruitment.uid_public.like(f"FCPI-{today_str}%")).count() + 1
            uid = f"FCPI-{today_str}-{str(count).zfill(3)}"

            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'fcpi', uid)
            os.makedirs(upload_path, exist_ok=True)

            def save_file(key, prefix):
                file = request.files.get(key)
                if file and file.filename != '':
                    fname = secure_filename(f"{prefix}_{file.filename}")
                    file.save(os.path.join(upload_path, fname))
                    return fname
                return None

            file_cv = save_file('cv_file', 'CV')
            file_fiche = save_file('job_desc_file', 'FICHE')
            file_photo = save_file('photo_file', 'PHOTO')

            # Parsing dates safe
            try:
                date_entree = datetime.strptime(request.form.get('date_entree'), '%Y-%m-%d')
            except:
                date_entree = datetime.utcnow()

            date_debut = None
            if request.form.get('date_debut_contrat'):
                try: date_debut = datetime.strptime(request.form.get('date_debut_contrat'), '%Y-%m-%d')
                except: pass
                
            date_fin = None
            if request.form.get('date_fin_contrat'):
                try: date_fin = datetime.strptime(request.form.get('date_fin_contrat'), '%Y-%m-%d')
                except: pass

            rec = Recruitment(
                uid_public=uid,
                author=current_user,
                status=RecruitmentStatus.WAITING_RH_MGR,
                nom_agent=request.form.get('nom_agent'),
                prenom_agent=request.form.get('prenom_agent'),
                date_entree=date_entree,
                fonction=request.form.get('fonction'),
                service_agent=request.form.get('service_affectation'),
                uf_agent=request.form.get('code_uf'),
                contractuel=(request.form.get('type_contrat') == 'Contractuel'),
                date_debut_contrat=date_debut,
                date_fin_contrat=date_fin,
                condition_recrutement=request.form.get('condition_recrutement'),
                temps_travail=request.form.get('temps_travail'),
                pourcentage_temps=request.form.get('pourcentage_temps'),
                motif_recrutement=request.form.get('motif_recrutement'),
                simulation_salaire=(request.form.get('simulation_salaire') == 'on'),
                localisation_poste=request.form.get('localisation_poste'),
                commentaire_securite=request.form.get('commentaire_securite'),
                imago_active=(request.form.get('imago_active') == 'on'),
                imago_mobilite=request.form.get('imago_mobilite'),
                materiels_demandes=request.form.get('materiel_list'),
                acces_informatique=request.form.get('acces_list'),
                file_cv=file_cv,
                file_fiche_poste=file_fiche,
                file_photo=file_photo
            )

            db.session.add(rec)
            db.session.commit()

            # Notification RH
            rh_managers = User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.ADMIN])).all()
            for u in rh_managers:
                if 'DRH' in u.get_allowed_services() or 'GS-DRH' in u.get_allowed_services():
                    n = Notification(user=u, message=f"Nouvelle FCPI à valider : {uid}", category='warning', link=url_for('tickets.manager_dashboard'))
                    db.session.add(n)
            db.session.commit()

            flash(f"Demande FCPI {uid} créée avec succès.", "success")
            return redirect(url_for('main.user_portal'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur creation FCPI: {e}")
            flash(f"Erreur création FCPI : {e}", "danger")
            return redirect(url_for('fcpi.new_fcpi'))

    return render_template('fcpi/new_request.html')

@fcpi_bp.route('/validate_director/<int:recruitment_id>', methods=['POST'])
@login_required
def validate_rh_director(recruitment_id):
    r = Recruitment.query.get_or_404(recruitment_id)
    
    # Vérification droits
    user_services = current_user.get_allowed_services()
    is_rh_auth = 'DRH' in user_services or 'GS-DRH' in user_services or 'ADMIN' in str(current_user.role)
    
    if not is_rh_auth:
        flash("Action non autorisée.", "danger")
        return redirect(url_for('tickets.manager_dashboard'))

    action = request.form.get('action')
    
    if action == 'refuse':
        r.status = RecruitmentStatus.REFUSED
        r.refusal_reason = request.form.get('reason', 'Refusé par la Direction RH')
        db.session.commit()
        flash("Demande de recrutement refusée.", "warning")
        return redirect(url_for('tickets.manager_dashboard'))

    elif action == 'validate':
        # --- LE GRAND DISPATCH (INTEGRÉ) ---
        child_ids = []
        try:
            # 1. TICKET DRH (Suffixe RH)
            desc_drh = (
                f"Nouvelle arrivée validée.\n"
                f"Contrat: {'Contractuel' if r.contractuel else 'Titulaire'}\n"
                f"Dates: {r.date_debut_contrat} au {r.date_fin_contrat}\n"
                f"Temps: {r.temps_travail} ({r.pourcentage_temps})\n"
                f"Salaire simu: {'Oui' if r.simulation_salaire else 'Non'}\n"
                f"Condition: {r.condition_recrutement}"
            )
            id_drh = create_sub_ticket(
                r, ServiceType.DRH, "Dossier Administratif", desc_drh,
                files_to_copy=[r.file_cv, r.file_fiche_poste],
                custom_suffix="RH"
            )
            child_ids.append(id_drh)

            # 2. TICKET INFORMATIQUE (Suffixe INF)
            desc_info = (
                f"Préparation poste informatique.\n"
                f"Service: {r.service_agent}\n"
                f"Localisation: {r.localisation_poste}\n"
            )
            id_info = create_sub_ticket(
                r, ServiceType.INFO, "Matériel & Accès", desc_info,
                specific_fields={
                    'materiel_list': r.materiels_demandes,
                    'new_user_acces': r.acces_informatique,
                    'lieu_installation': r.localisation_poste,
                    'destinataire_materiel': f"{r.nom_agent} {r.prenom_agent}"
                },
                custom_suffix="INF"
            )
            child_ids.append(id_info)

            # 3. TICKET SÉCURITÉ (Suffixe SEC)
            desc_secu = (
                f"Création de badge et accès physiques.\n"
                f"Localisation: {r.localisation_poste}\n"
                f"Commentaire: {r.commentaire_securite}"
            )
            id_secu = create_sub_ticket(
                r, ServiceType.SECU, "Badge & Accès", desc_secu,
                files_to_copy=[r.file_photo],
                custom_suffix="SEC"
            )
            child_ids.append(id_secu)

            # 4. TICKET IMAGO (Suffixe IMA)
            if r.imago_active:
                desc_imago = (
                    f"Création compte IMAGO.\n"
                    f"Mobilité: {r.imago_mobilite}"
                )
                id_imago = create_sub_ticket(
                    r, ServiceType.IMAGO, "Compte Imago", desc_imago,
                    custom_suffix="IMA"
                )
                child_ids.append(id_imago)

            r.status = RecruitmentStatus.DISPATCHED
            r.child_tickets_ids = json.dumps(child_ids)
            
            # Notification User (Manager Demandeur)
            n = Notification(user=r.author, message=f"FCPI {r.uid_public} validée ! Les tickets ont été créés.", category='success', link=url_for('fcpi.view_fcpi', uid=r.uid_public))
            db.session.add(n)
            
            db.session.commit()
            flash(f"Demande validée ! {len(child_ids)} tickets ont été dispatchés.", "success")
            
        except Exception as e:
            db.session.rollback()
            print(f"ERREUR DISPATCH: {e}")
            flash(f"Erreur critique lors du dispatch : {str(e)}", "danger")
            
        return redirect(url_for('tickets.manager_dashboard'))

    return redirect(url_for('tickets.manager_dashboard'))

@fcpi_bp.route('/view/<string:uid>')
@login_required
def view_fcpi(uid):
    r = Recruitment.query.filter_by(uid_public=uid).first_or_404()
    return render_template('fcpi/view_detail.html', r=r)
