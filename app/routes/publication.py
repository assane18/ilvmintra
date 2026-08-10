from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models import Publication, PublicationStatus, User, UserRole, Notification
from app import db
from werkzeug.utils import secure_filename
import os, json
from datetime import datetime

publication_bp = Blueprint('publication', __name__)


# ─────────────────────────────────────────────
# CRÉATION (Manager / Coordinateur)
# ─────────────────────────────────────────────

@publication_bp.route('/publication/new', methods=['GET', 'POST'])
@login_required
def new_publication():
    role = str(current_user.role.value).upper()
    if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
        flash("La création d'une publication est réservée aux responsables et coordinateurs.", "danger")
        return redirect(url_for('main.user_portal'))

    if request.method == 'POST':
        today_str = datetime.now().strftime('%Y%m%d')
        count = Publication.query.filter(
            Publication.uid_public.like(f"PUB-{today_str}%")
        ).count() + 1
        uid = f"PUB-{today_str}-{str(count).zfill(3)}"

        upload_path = os.path.join(
            current_app.root_path, 'static', 'uploads', 'publications', uid
        )
        os.makedirs(upload_path, exist_ok=True)

        # Sauvegarde des visuels (multi-fichiers)
        files_saved = []
        for f in request.files.getlist('visuels'):
            if f and f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(upload_path, fname))
                files_saved.append(fname)

        pub = Publication(
            uid_public=uid,
            author=current_user,
            status=PublicationStatus.VALIDATION_DIRECTEUR,
            titre=request.form.get('titre'),
            contenu=request.form.get('contenu'),
            files_json=json.dumps(files_saved),
        )
        db.session.add(pub)
        db.session.commit()

        # Notifier les Directeurs
        directeurs = User.query.filter(
            (User.role == UserRole.DIRECTEUR) | (User.role == UserRole.ADMIN)
        ).all()
        for d in directeurs:
            n = Notification(
                user=d,
                message=f"Nouvelle publication à valider : {uid}",
                category='info',
                link=url_for('publication.view_publication', id=pub.id)
            )
            db.session.add(n)
        db.session.commit()

        flash("Publication soumise. En attente de validation du Directeur.", "success")
        return redirect(url_for('main.user_portal'))

    return render_template('publication/new_publication.html')


# ─────────────────────────────────────────────
# VISUALISATION
# ─────────────────────────────────────────────

@publication_bp.route('/publication/view/<int:id>')
@login_required
def view_publication(id):
    pub = Publication.query.get_or_404(id)
    role = str(current_user.role.value).upper()
    is_manager = 'MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role
    is_communication = 'COMMUNICATION' in current_user.get_allowed_services()

    if pub.author_id != current_user.id and not is_manager and not is_communication:
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('main.user_portal'))

    return render_template('publication/view_publication.html',
                           pub=pub,
                           is_manager=is_manager,
                           is_communication=is_communication)


# ─────────────────────────────────────────────
# VALIDATION / REFUS (Directeur)
# ─────────────────────────────────────────────

@publication_bp.route('/publication/validate/<int:id>/<action>', methods=['POST'])
@login_required
def validate_publication(id, action):
    pub = Publication.query.get_or_404(id)
    role = str(current_user.role.value).upper()

    if not ('DIRECTEUR' in role or 'ADMIN' in role):
        flash("Validation réservée au Directeur.", "danger")
        return redirect(url_for('publication.view_publication', id=pub.id))

    if action == 'refuse':
        pub.status = PublicationStatus.REFUSE
        pub.refusal_reason = request.form.get('refusal_reason', 'Refusé.')
        n = Notification(
            user=pub.author,
            message=f"Votre publication {pub.uid_public} a été refusée.",
            category='danger',
            link=url_for('publication.view_publication', id=pub.id)
        )
        db.session.add(n)
        db.session.commit()
        flash("Publication refusée.", "warning")

    elif action == 'validate' and pub.status == PublicationStatus.VALIDATION_DIRECTEUR:
        pub.status = PublicationStatus.EN_CORRECTION

        # Notifier le service Communication
        com_users = [u for u in User.query.all()
                     if 'COMMUNICATION' in u.get_allowed_services()]
        for u in com_users:
            n = Notification(
                user=u,
                message=f"Publication {pub.uid_public} validée, à mettre en page.",
                category='info',
                link=url_for('publication.view_publication', id=pub.id)
            )
            db.session.add(n)

        n_author = Notification(
            user=pub.author,
            message=f"Votre publication {pub.uid_public} a été validée et transmise à la Communication.",
            category='success',
            link=url_for('publication.view_publication', id=pub.id)
        )
        db.session.add(n_author)
        db.session.commit()
        flash("Publication validée et transmise à la Communication.", "success")

    return redirect(url_for('tickets.manager_dashboard'))


# ─────────────────────────────────────────────
# PUBLICATION FINALE (Communication)
# ─────────────────────────────────────────────

@publication_bp.route('/publication/publish/<int:id>', methods=['POST'])
@login_required
def publish(id):
    pub = Publication.query.get_or_404(id)
    role = str(current_user.role.value).upper()
    is_communication = 'COMMUNICATION' in current_user.get_allowed_services()

    if not (is_communication or 'ADMIN' in role):
        flash("Action réservée au service Communication.", "danger")
        return redirect(url_for('publication.view_publication', id=pub.id))

    pub.status = PublicationStatus.PUBLIE
    pub.communication_notes = request.form.get('communication_notes', '')

    n = Notification(
        user=pub.author,
        message=f"Votre publication {pub.uid_public} a été publiée.",
        category='success',
        link=url_for('publication.view_publication', id=pub.id)
    )
    db.session.add(n)
    db.session.commit()
    flash("Publication mise en ligne avec succès.", "success")
    return redirect(url_for('publication.view_publication', id=pub.id))
