from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models import Recruitment, RecruitmentStatus, UserRole, ServiceType, Ticket, TicketStatus, User, Notification
from app import db
from werkzeug.utils import secure_filename
import os, json
from datetime import datetime

fcpi_bp = Blueprint('fcpi', __name__)

def create_sub_ticket(recruitment, target_service, title, description, custom_suffix=None):
    """
    Crée un ticket pour un service spécifique.
    """
    # Si aucun suffixe n'est fourni, on prend les 3 premières lettres du service
    suffix = custom_suffix if custom_suffix else target_service.value[:3]
    
    t = Ticket(
        uid_public=f"{recruitment.uid_public}-{suffix}",
        title=f"[FCPI] {title} - {recruitment.nom_agent} {recruitment.prenom_agent}",
        description=description,
        author_id=recruitment.author_id,
        target_service=target_service, # <-- C'est ici que le service destinataire est défini
        status=TicketStatus.PENDING,
        category_ticket="Nouvel Utilisateur"
    )
    db.session.add(t)
    db.session.flush() 
    return t.id

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

        rec = Recruitment(
            uid_public=uid,
            author=current_user,
            status=RecruitmentStatus.WAITING_RH_MGR,
            date_entree=datetime.strptime(request.form.get('date_entree'), '%Y-%m-%d'),
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

        # LOGIQUE REFUS
        if action == 'refuse':
            rec.status = RecruitmentStatus.REFUSED
            rec.refusal_reason = f"Refusé par {current_user.fullname} : {comment}"
            n = Notification(user=rec.author, message=f"Votre FCPI {rec.uid_public} a été refusée.", category='danger', link=url_for('fcpi.view_fcpi', id=rec.id))
            db.session.add(n)
            db.session.commit()
            flash("Demande refusée et renvoyée au demandeur.", "warning")
            return redirect(url_for('main.user_portal'))

        # LOGIQUE VALIDATION
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
                # VALIDATION FINALE -> DISPATCH AUX SERVICES
                rec.status = RecruitmentStatus.DISPATCHED
                child_ids = []
                
                def file_link(filename):
                    if not filename: return "Aucun"
                    return f"/static/uploads/fcpi/{rec.uid_public}/{filename}"

                # 1. DRH -> ServiceType.DRH
                desc_drh = (
                    f"--- NOUVEAU RECRUTEMENT ---\n"
                    f"Agent: {rec.nom_agent} {rec.prenom_agent}\n"
                    f"Date entrée: {rec.date_entree.strftime('%d/%m/%Y')}\n"
                    f"Contrat: {'Contractuel' if rec.contractuel else 'Titulaire'}\n"
                    f"Du {rec.date_debut_contrat.strftime('%d/%m/%Y') if rec.date_debut_contrat else '?'} au {rec.date_fin_contrat.strftime('%d/%m/%Y') if rec.date_fin_contrat else '?'}\n"
                    f"Salaire simu: {'OUI' if rec.simulation_salaire else 'NON'}\n\n"
                    f"--- PIÈCES JOINTES (Copier le lien) ---\n"
                    f"CV: {request.host_url}{file_link(rec.file_cv)}\n"
                    f"Fiche Poste: {request.host_url}{file_link(rec.file_fiche_poste)}"
                )
                child_ids.append(create_sub_ticket(rec, ServiceType.DRH, "Dossier Administratif", desc_drh, custom_suffix="DRH"))
                
                # 2. SÉCURITÉ -> ServiceType.SECU
                desc_secu = (
                    f"Agent: {rec.nom_agent} {rec.prenom_agent}\n"
                    f"Service: {rec.service_agent}\n"
                    f"Date entrée: {rec.date_entree.strftime('%d/%m/%Y')}\n"
                    f"Localisation: {rec.localisation_poste}\n"
                    f"Besoins Badge/Clés: {rec.commentaire_securite}\n\n"
                    f"PHOTO AGENT (Copier le lien): {request.host_url}{file_link(rec.file_photo)}"
                )
                child_ids.append(create_sub_ticket(rec, ServiceType.SECU, "Badge & Accès", desc_secu, custom_suffix="SEC"))
                
                # 3. INFORMATIQUE -> ServiceType.INFO
                desc_info = (
                    f"Agent: {rec.nom_agent} {rec.prenom_agent}\n"
                    f"Service: {rec.service_agent}\n"
                    f"Date entrée: {rec.date_entree.strftime('%d/%m/%Y')}\n"
                    f"Matériel demandé: {rec.materiels_demandes}\n"
                    f"Accès logiciels/réseaux: {rec.acces_informatique}\n"
                )
                child_ids.append(create_sub_ticket(rec, ServiceType.INFO, "Matériel & Accès", desc_info, custom_suffix="INF"))
                
                # 4. IMAGO -> ServiceType.IMAGO (Directement au service Imago)
                if rec.imago_active:
                    desc_imago = (
                        f"Création compte Imago pour {rec.nom_agent} {rec.prenom_agent}.\n"
                        f"Mobilité (Sites): {rec.imago_mobilite}"
                    )
                    child_ids.append(create_sub_ticket(rec, ServiceType.IMAGO, "Compte Imago", desc_imago, custom_suffix="IMA"))
                
                rec.child_tickets_ids = json.dumps(child_ids)
                
                n = Notification(user=rec.author, message=f"FCPI {rec.uid_public} validée ! Les services sont informés.", category='success', link=url_for('fcpi.view_fcpi', id=rec.id))
                db.session.add(n)
                
                flash("FCPI Validée ! Les tickets ont été envoyés aux services dédiés.", "success")
                
            else:
                flash("Droit Directeur RH requis.", "danger")

        # COMMIT FINAL UNIQUE
        db.session.commit()
        return redirect(url_for('main.user_portal'))

    except Exception as e:
        db.session.rollback() # Annule tout si une erreur survient
        current_app.logger.error(f"Erreur validation FCPI: {e}")
        flash(f"Erreur serveur lors de la validation : {e}", "danger")
        return redirect(url_for('fcpi.view_fcpi', id=id))
