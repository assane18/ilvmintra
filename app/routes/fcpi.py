from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models import Recruitment, RecruitmentStatus, UserRole, ServiceType, Ticket, TicketStatus, User, Notification
from app import db
from werkzeug.utils import secure_filename
import os, json, shutil
from datetime import datetime

fcpi_bp = Blueprint('fcpi', __name__)

# --- FONCTION UTILITAIRE BLINDÉE (Anti-Doublon) ---
def create_sub_ticket(recruitment, target_service, title, description, specific_fields=None, files_to_copy=None, custom_suffix=None):
    """
    Crée un ticket ou le met à jour s'il existe déjà (évite les doublons).
    """
    # 1. Génération de l'ID unique
    suffix = custom_suffix if custom_suffix else target_service.value[:3]
    unique_uid = f"{recruitment.uid_public}-{suffix}"
    
    # 2. VÉRIFICATION ANTI-DOUBLON (Le fix est ici)
    existing_ticket = Ticket.query.filter_by(uid_public=unique_uid).first()
    
    full_title = f"[FCPI] {title} - {recruitment.nom_agent} {recruitment.prenom_agent}"

    if existing_ticket:
        # Si le ticket existe déjà (créé par erreur par un autre script), on le met juste à jour
        t = existing_ticket
        t.title = full_title # On force le bon titre [FCPI]
        t.description = description
        # On ne recrée pas l'objet, on le met à jour
        print(f"DEBUG: Ticket {unique_uid} existait déjà, mise à jour effectuée.")
    else:
        # Création normale
        t = Ticket(
            uid_public=unique_uid,
            title=full_title,
            description=description,
            author_id=recruitment.author_id,
            target_service=target_service,
            status=TicketStatus.PENDING,
            category_ticket="Nouvel Utilisateur",
            service_demandeur=recruitment.service_agent,
            new_user_fullname=f"{recruitment.nom_agent} {recruitment.prenom_agent}",
            new_user_service=recruitment.service_agent,
            new_user_date=recruitment.date_entree,
            created_at=datetime.utcnow()
        )

    # 3. Injection des données avancées
    if specific_fields:
        if 'materiel_list' in specific_fields: t.materiel_list = specific_fields['materiel_list']
        if 'new_user_acces' in specific_fields: t.new_user_acces = specific_fields['new_user_acces']
        if 'lieu_installation' in specific_fields: t.lieu_installation = specific_fields['lieu_installation']
        if 'destinataire_materiel' in specific_fields: t.destinataire_materiel = specific_fields['destinataire_materiel']

    # 4. Copie physique des fichiers (Avec sécurité)
    ticket_files_list = []
    if files_to_copy:
        base_upload_path = os.path.join(current_app.root_path, 'static', 'uploads')
        src_dir = os.path.join(base_upload_path, 'fcpi', recruitment.uid_public)
        dest_dir = os.path.join(base_upload_path, 'tickets', unique_uid)
        
        if os.path.exists(src_dir):
            try:
                os.makedirs(dest_dir, exist_ok=True)
                for filename in files_to_copy:
                    if filename:
                        src_file = os.path.join(src_dir, filename)
                        if os.path.exists(src_file):
                            shutil.copy2(src_file, dest_dir)
                            ticket_files_list.append(filename)
            except Exception as e:
                print(f"Erreur copie fichier pour {unique_uid}: {e}")

    if ticket_files_list:
        t.daf_files_json = json.dumps(ticket_files_list)

    if not existing_ticket:
        db.session.add(t)
    
    db.session.flush() 
    return t.id

# --- ROUTES ---

@fcpi_bp.route('/fcpi/check_access')
@login_required
def check_access():
    role = str(current_user.role.value).upper()
    if 'MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role:
        return redirect(url_for('fcpi.new_fcpi'))
    else:
        return render_template('errors/catdance.html'), 403

@fcpi_bp.route('/fcpi/new', methods=['GET', 'POST'])
@login_required
def new_fcpi():
    role = str(current_user.role.value).upper()
    if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
        return render_template('errors/catdance.html'), 403

    if request.method == 'POST':
        today_str = datetime.now().strftime('%Y%m%d')
        try:
            count = Recruitment.query.filter(Recruitment.uid_public.like(f"FCPI-{today_str}%")).count() + 1
        except:
            count = 1
        uid = f"FCPI-{today_str}-{str(count).zfill(3)}"
        
        upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'fcpi', uid)
        os.makedirs(upload_path, exist_ok=True)
        
        def save_file(key):
            f = request.files.get(key)
            if f and f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(upload_path, fname))
                return fname
            return None

        d_entree = datetime.utcnow()
        if request.form.get('date_entree'):
             try: d_entree = datetime.strptime(request.form.get('date_entree'), '%Y-%m-%d')
             except: pass

        rec = Recruitment(
            uid_public=uid,
            author=current_user,
            status=RecruitmentStatus.WAITING_RH_MGR,
            date_entree=d_entree,
            nom_agent=request.form.get('nom'),
            prenom_agent=request.form.get('prenom'),
            fonction=request.form.get('fonction'),
            service_agent=request.form.get('service'),
            uf_agent=request.form.get('uf'),
            contractuel=(request.form.get('contractuel') == 'oui'),
            condition_recrutement=request.form.get('condition'),
            temps_travail=request.form.get('temps_travail'),
            pourcentage_temps=request.form.get('pourcentage'),
            motif_recrutement=request.form.get('motif'),
            simulation_salaire=(request.form.get('simulation') == 'oui'),
            localisation_poste=request.form.get('localisation'),
            commentaire_securite=request.form.get('commentaire_secu'),
            imago_active=(request.form.get('imago') == 'oui'),
            imago_mobilite=request.form.get('imago_mobilite'),
            materiels_demandes=",".join(request.form.getlist('materiel_type')),
            acces_informatique=request.form.get('acces_info'),
            file_cv=save_file('cv_file'),
            file_fiche_poste=save_file('fiche_poste_file'),
            file_photo=save_file('photo_file')
        )
        
        if request.form.get('date_debut_contrat'):
            try: rec.date_debut_contrat = datetime.strptime(request.form.get('date_debut_contrat'), '%Y-%m-%d')
            except: pass
        if request.form.get('date_fin_contrat'):
            try: rec.date_fin_contrat = datetime.strptime(request.form.get('date_fin_contrat'), '%Y-%m-%d')
            except: pass

        db.session.add(rec)
        db.session.commit()
        
        candidates = User.query.filter((User.role == UserRole.MANAGER) | (User.role == UserRole.ADMIN)).all()
        rh_users = [u for u in candidates if 'DRH' in u.get_allowed_services() or 'RH' in u.get_allowed_services()]

        for u in rh_users:
            if 'MANAGER' in str(u.role.value).upper() or 'ADMIN' in str(u.role.value).upper():
                n = Notification(user=u, message=f"Nouveau FCPI à valider : {uid}", link=url_for('fcpi.view_fcpi', id=rec.id))
                db.session.add(n)
        db.session.commit()

        flash("Demande FCPI créée. En attente de validation RH Manager.", "success")
        return redirect(url_for('main.user_portal'))

    return render_template('fcpi/new_fcpi.html')

@fcpi_bp.route('/fcpi/view/<int:id>', methods=['GET'])
@login_required
def view_fcpi(id):
    rec = Recruitment.query.get_or_404(id)
    user_svcs = current_user.get_allowed_services()
    is_rh = 'DRH' in user_svcs or 'RH' in user_svcs
    is_admin = 'ADMIN' in str(current_user.role.value).upper()
    
    if rec.author_id != current_user.id and not is_rh and not is_admin:
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('main.user_portal'))
        
    return render_template('fcpi/view_fcpi.html', rec=rec)

@fcpi_bp.route('/fcpi/validate/<int:id>/<action>', methods=['POST'])
@login_required
def validate_fcpi(id, action):
    try:
        rec = Recruitment.query.get_or_404(id)
        comment = request.form.get('refusal_comment', '')
        
        user_services = current_user.get_allowed_services()
        is_rh = 'DRH' in user_services or 'RH' in user_services
        is_admin = 'ADMIN' in str(current_user.role.value).upper()
        role = str(current_user.role.value).upper()
        
        if not (is_rh or is_admin):
            flash("Action réservée au service RH.", "danger")
            return redirect(url_for('main.user_portal'))

        if action == 'refuse':
            rec.status = RecruitmentStatus.REFUSED
            rec.refusal_reason = f"Refusé par {current_user.fullname} : {comment}"
            n = Notification(user=rec.author, message=f"Votre FCPI {rec.uid_public} a été refusée.", category='danger', link=url_for('fcpi.view_fcpi', id=rec.id))
            db.session.add(n)
            db.session.commit()
            flash("Demande refusée et renvoyée au demandeur.", "warning")
            return redirect(url_for('main.user_portal'))

        if rec.status == RecruitmentStatus.WAITING_RH_MGR:
            if 'MANAGER' in role or 'ADMIN' in role:
                rec.status = RecruitmentStatus.WAITING_RH_DIR
                flash("Validé par Manager RH. En attente Directeur RH.", "success")
                
                dir_rh = User.query.filter((User.role == UserRole.DIRECTEUR) | (User.role == UserRole.ADMIN)).all()
                for u in dir_rh:
                     if 'DRH' in u.get_allowed_services() or 'RH' in u.get_allowed_services() or 'ADMIN' in str(u.role.value):
                         n = Notification(user=u, message=f"FCPI {rec.uid_public} (Validé N1) en attente signature.", link=url_for('fcpi.view_fcpi', id=rec.id))
                         db.session.add(n)
            else:
                 flash("Droit Manager RH requis.", "danger")

        elif rec.status == RecruitmentStatus.WAITING_RH_DIR:
            if 'DIRECTEUR' in role or 'ADMIN' in role:
                rec.status = RecruitmentStatus.DISPATCHED
                child_ids = []
                
                # 1. TICKET DRH
                desc_drh = (
                    f"Nouvelle arrivée validée.\n"
                    f"Contrat: {'Contractuel' if rec.contractuel else 'Titulaire'}\n"
                    f"Temps: {rec.temps_travail} ({rec.pourcentage_temps})\n"
                    f"Salaire simu: {'Oui' if rec.simulation_salaire else 'Non'}\n"
                    f"Condition: {rec.condition_recrutement}"
                )
                child_ids.append(create_sub_ticket(
                    rec, ServiceType.DRH, "Dossier Administratif", desc_drh,
                    files_to_copy=[rec.file_cv, rec.file_fiche_poste],
                    custom_suffix="DRH"
                ))
                
                # 2. TICKET INFORMATIQUE
                desc_info = (
                    f"Préparation poste informatique.\n"
                    f"Service: {rec.service_agent}\n"
                    f"Localisation: {rec.localisation_poste}\n"
                    f"Matériel demandé: {rec.materiels_demandes}"
                )
                info_specs = {
                    'materiel_list': rec.materiels_demandes,
                    'new_user_acces': rec.acces_informatique,
                    'lieu_installation': rec.localisation_poste,
                    'destinataire_materiel': f"{rec.nom_agent} {rec.prenom_agent}"
                }
                child_ids.append(create_sub_ticket(
                    rec, ServiceType.INFO, "Matériel & Accès", desc_info,
                    specific_fields=info_specs,
                    custom_suffix="INF"
                ))
                
                # 3. TICKET SÉCURITÉ
                desc_secu = (
                    f"Création de badge et accès physiques.\n"
                    f"Localisation: {rec.localisation_poste}\n"
                    f"Commentaire: {rec.commentaire_securite}"
                )
                secu_specs = {'lieu_installation': rec.localisation_poste}
                child_ids.append(create_sub_ticket(
                    rec, ServiceType.SECU, "Badge & Accès", desc_secu,
                    specific_fields=secu_specs,
                    files_to_copy=[rec.file_photo],
                    custom_suffix="SEC"
                ))
                
                # 4. TICKET IMAGO
                if rec.imago_active:
                    desc_imago = f"Création compte IMAGO. Mobilité: {rec.imago_mobilite}"
                    child_ids.append(create_sub_ticket(
                        rec, ServiceType.IMAGO, "Compte Imago", desc_imago,
                        custom_suffix="IMA"
                    ))
                
                rec.child_tickets_ids = json.dumps(child_ids)
                
                n = Notification(user=rec.author, message=f"FCPI {rec.uid_public} validée ! Les tickets ont été créés.", category='success', link=url_for('fcpi.view_fcpi', id=rec.id))
                db.session.add(n)
                
                flash(f"FCPI Validée ! {len(child_ids)} tickets générés.", "success")
                
            else:
                flash("Droit Directeur RH requis.", "danger")

        db.session.commit()
        return redirect(url_for('main.user_portal'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur validation FCPI: {e}")
        flash(f"Erreur technique lors du dispatch : {str(e)}", "danger")
        return redirect(url_for('fcpi.view_fcpi', id=id))
