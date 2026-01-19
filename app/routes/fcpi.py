from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models import Recruitment, RecruitmentStatus, UserRole, ServiceType, Ticket, TicketStatus, User, Notification
from app import db
from werkzeug.utils import secure_filename
import os, json
from datetime import datetime

fcpi_bp = Blueprint('fcpi', __name__)

def create_sub_ticket(recruitment, target_service, title, description):
    """Crée un ticket standard pour un service technique basé sur le FCPI"""
    t = Ticket(
        uid_public=f"{recruitment.uid_public}-{target_service.value[:3]}",
        title=f"[FCPI] {title} - {recruitment.nom_agent} {recruitment.prenom_agent}",
        description=description,
        author_id=recruitment.author_id, # Le demandeur initial reste l'auteur
        target_service=target_service,
        status=TicketStatus.PENDING,
        category_ticket="Nouvel Utilisateur"
    )
    db.session.add(t)
    db.session.commit()
    return t.id

@fcpi_bp.route('/fcpi/check_access')
@login_required
def check_access():
    """Route intermédiaire pour le piège Catdance"""
    role = str(current_user.role.value).upper()
    # Seuls MANAGER et DIRECTEUR passent, les autres -> Catdance
    # ADMIN passe aussi pour debug
    if 'MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role:
        return redirect(url_for('fcpi.new_fcpi'))
    else:
        return render_template('errors/catdance.html'), 403

@fcpi_bp.route('/fcpi/new', methods=['GET', 'POST'])
@login_required
def new_fcpi():
    # Double sécurité
    role = str(current_user.role.value).upper()
    if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
        return render_template('errors/catdance.html'), 403

    if request.method == 'POST':
        # Génération UID
        today_str = datetime.now().strftime('%Y%m%d')
        # On compte les FCPI du jour
        try:
            count = Recruitment.query.filter(Recruitment.uid_public.like(f"FCPI-{today_str}%")).count() + 1
        except:
            count = 1
        uid = f"FCPI-{today_str}-{str(count).zfill(3)}"
        
        # Gestion Fichiers
        upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'fcpi', uid)
        os.makedirs(upload_path, exist_ok=True)
        
        def save_file(key):
            f = request.files.get(key)
            if f and f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(upload_path, fname))
                return fname
            return None

        # Création Objet
        rec = Recruitment(
            uid_public=uid,
            author=current_user,
            status=RecruitmentStatus.WAITING_RH_MGR,
            
            # Agent
            date_entree=datetime.strptime(request.form.get('date_entree'), '%Y-%m-%d'),
            nom_agent=request.form.get('nom'),
            prenom_agent=request.form.get('prenom'),
            fonction=request.form.get('fonction'),
            service_agent=request.form.get('service'),
            uf_agent=request.form.get('uf'),
            
            # DRH
            contractuel=(request.form.get('contractuel') == 'oui'),
            condition_recrutement=request.form.get('condition'),
            temps_travail=request.form.get('temps_travail'),
            pourcentage_temps=request.form.get('pourcentage'),
            motif_recrutement=request.form.get('motif'),
            simulation_salaire=(request.form.get('simulation') == 'oui'),
            
            # Badge/Secu
            localisation_poste=request.form.get('localisation'),
            commentaire_securite=request.form.get('commentaire_secu'),
            
            # Imago
            imago_active=(request.form.get('imago') == 'oui'),
            imago_mobilite=request.form.get('imago_mobilite'),
            
            # Info
            materiels_demandes=",".join(request.form.getlist('materiel_type')),
            acces_informatique=request.form.get('acces_info'),
            
            # Files
            file_cv=save_file('cv_file'),
            file_fiche_poste=save_file('fiche_poste_file'),
            file_photo=save_file('photo_file')
        )
        
        # Dates conditionnelles
        if request.form.get('date_debut_contrat'):
            try: rec.date_debut_contrat = datetime.strptime(request.form.get('date_debut_contrat'), '%Y-%m-%d')
            except: pass
        if request.form.get('date_fin_contrat'):
            try: rec.date_fin_contrat = datetime.strptime(request.form.get('date_fin_contrat'), '%Y-%m-%d')
            except: pass

        db.session.add(rec)
        db.session.commit()
        
        # Notification aux RH Managers (CORRECTIF: Filtrage Python)
        # On récupère d'abord tous les Managers et Admins
        candidates = User.query.filter((User.role == UserRole.MANAGER) | (User.role == UserRole.ADMIN)).all()
        # On filtre ensuite ceux qui ont le service RH ou DRH
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
    # Sécurité visualisation
    # Peut voir : Auteur, Admin, ou membres du service RH (Manager/Directeur)
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
    rec = Recruitment.query.get_or_404(id)
    comment = request.form.get('refusal_comment', '')
    
    # Vérification Droits RH (Validation nécessite d'être RH ou Admin)
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
        
        # Notification au demandeur
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
            
            # Notif Directeur RH
            dir_rh = User.query.filter((User.role == UserRole.DIRECTEUR) | (User.role == UserRole.ADMIN)).all()
            for u in dir_rh:
                 if 'DRH' in u.get_allowed_services() or 'RH' in u.get_allowed_services() or 'ADMIN' in str(u.role.value):
                     n = Notification(user=u, message=f"FCPI {rec.uid_public} (Validé N1) en attente signature.", link=url_for('fcpi.view_fcpi', id=rec.id))
                     db.session.add(n)
                     
        else:
             flash("Droit Manager RH requis.", "danger")

    elif rec.status == RecruitmentStatus.WAITING_RH_DIR:
        if 'DIRECTEUR' in role or 'ADMIN' in role:
            # VALIDATION FINALE -> DISPATCH
            rec.status = RecruitmentStatus.DISPATCHED
            child_ids = []
            
            # 1. Ticket GESTIONNAIRE DRH (Données + DRH)
            desc_drh = f"Nouvel Agent: {rec.nom_agent} {rec.prenom_agent}\nContrat: {'Contractuel' if rec.contractuel else 'Titulaire'}\nEntrée: {rec.date_entree.strftime('%d/%m/%Y')}\nVoir FCPI pour pièces jointes."
            child_ids.append(create_sub_ticket(rec, ServiceType.DRH, "Dossier Administratif", desc_drh))
            
            # 2. Ticket SÉCURITÉ (Badge & Contrôle accès)
            desc_secu = f"Nouvel Agent: {rec.nom_agent} {rec.prenom_agent}\nDate: {rec.date_entree.strftime('%d/%m/%Y')}\nLocalisation: {rec.localisation_poste}\nCommentaire: {rec.commentaire_securite}\nPhoto fournie dans FCPI."
            child_ids.append(create_sub_ticket(rec, ServiceType.SECU, "Badge & Accès", desc_secu))
            
            # 3. Ticket INFORMATIQUE (Données + Info)
            desc_info = f"Nouvel Agent: {rec.nom_agent} {rec.prenom_agent}\nDate: {rec.date_entree.strftime('%d/%m/%Y')}\nMatériel: {rec.materiels_demandes}\nAccès: {rec.acces_informatique}"
            child_ids.append(create_sub_ticket(rec, ServiceType.INFO, "Matériel & Accès", desc_info))
            
            # 4. Ticket IMAGO (Si coché) -> Assigné à INFO ou IMAGO si existe
            if rec.imago_active:
                desc_imago = f"Création compte Imago pour {rec.nom_agent} {rec.prenom_agent}.\nMobilité: {rec.imago_mobilite}"
                child_ids.append(create_sub_ticket(rec, ServiceType.INFO, "Compte Imago", desc_imago))
            
            rec.child_tickets_ids = json.dumps(child_ids)
            
            # Notif Auteur
            n = Notification(user=rec.author, message=f"FCPI {rec.uid_public} validée ! Les services sont informés.", category='success', link=url_for('fcpi.view_fcpi', id=rec.id))
            db.session.add(n)
            
            flash("FCPI Validée ! Les tickets ont été envoyés aux services.", "success")
            
        else:
            flash("Droit Directeur RH requis.", "danger")

    db.session.commit()
    return redirect(url_for('main.user_portal'))
