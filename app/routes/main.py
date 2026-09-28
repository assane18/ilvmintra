from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_from_directory, current_app
import os
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from app.models import UserRole, Ticket, FormDefinition, User, FormSubmission, FormSubmissionStatus, ServiceType, TicketStatus
from app import db
from app.decorators import admin_required
from app.health import get_liveness, get_full_health
from app.routes.tickets import generate_ticket_uid, notify_solvers_new_ticket, get_service_emails, get_paris_time
from app.emails import send_service_alert
import json

main_bp = Blueprint('main', __name__)

# Palette de couleurs d'accent proposée dans la page profil (onglet Apparence).
# (clé, libellé, hex de la pastille) — les valeurs CSS réelles de chaque thème
# sont dans base.html (html[data-theme-color="..."]). Whitelist stricte côté
# serveur via PROFILE_THEME_COLORS.
PROFILE_THEME_PALETTE = [
    ('teal', 'Turquoise', '#0d9488'),
    ('blue', 'Bleu', '#2563eb'),
    ('indigo', 'Indigo', '#4f46e5'),
    ('violet', 'Violet', '#7c3aed'),
    ('fuchsia', 'Fuchsia', '#c026d3'),
    ('rose', 'Rose', '#e11d48'),
    ('orange', 'Orange', '#ea580c'),
    ('amber', 'Ambre', '#d97706'),
    ('emerald', 'Émeraude', '#059669'),
    ('lime', 'Citron vert', '#65a30d'),
]
PROFILE_THEME_COLORS = {c for c, _, _ in PROFILE_THEME_PALETTE}
PROFILE_THEME_MODES = {'light', 'dark', 'auto'}
PROFILE_FONT_SCALES = {'normal', 'large', 'xlarge'}
PROFILE_DENSITIES = {'comfortable', 'compact'}
PROFILE_PHOTO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
PROFILE_BUG_TYPES = ['Erreur', 'Affichage', 'Lenteur', 'Suggestion']

# Pilotes du moteur de formulaires déjà basculés en direct avec leur propre
# tuile dédiée dans portal.html (icône/texte historique conservés, juste le
# lien qui pointe désormais vers forms.new_submission) — à exclure de la
# boucle active_forms générique ci-dessous pour ne pas les afficher deux fois.
LIVE_PILOT_SLUGS = {'info-v2', 'imago-v2', 'drh-v2', 'materiel-v2', 'tech-v2', 'generaux-v2', 'sejour-v2', 'publication-v2'}

@main_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    return redirect(url_for('main.user_portal'))

@main_bp.route('/portal')
@login_required
def user_portal():
    # Les 15 dernières demandes de l'utilisateur (tickets + soumissions en
    # attente de validation — voir _user_history_items).
    recent_items = _user_history_items(current_user)[:15]

    active_forms = FormDefinition.query.filter_by(is_active=True)\
        .filter(FormDefinition.slug.notin_(LIVE_PILOT_SLUGS))\
        .order_by(FormDefinition.name).all()

    return render_template('portal.html', user=current_user, items=recent_items, active_forms=active_forms)

def _ticket_status_class(status_value):
    if 'VALIDATION' in status_value:
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300'
    if 'COURS' in status_value:
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
    if 'TERMINE' in status_value:
        return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
    return 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-300'


def _user_history_items(user, search_query=''):
    """Historique unifié d'un utilisateur : ses Tickets + ses FormSubmission
    qui n'ont PAS encore de ticket (en attente de validation, refusées, ou
    finalisées sans aucun destinataire configuré). Sans ce 2e volet, une
    demande passée par le moteur de formulaires reste invisible tant
    qu'aucune étape n'a été validée — contrairement à l'ancien système qui
    créait le ticket dès la soumission (statut "en attente"). Utilisé par le
    portail (aperçu limité) et par /my_history (liste complète filtrable)."""
    ticket_query = Ticket.query.filter_by(author_id=user.id)
    if search_query:
        ticket_query = ticket_query.filter(
            db.or_(
                Ticket.title.ilike(f'%{search_query}%'),
                Ticket.uid_public.ilike(f'%{search_query}%'),
                Ticket.description.ilike(f'%{search_query}%')
            )
        )
    items = []
    for t in ticket_query.all():
        items.append({
            'ref': t.uid_public,
            'date': t.created_at,
            'service': t.target_service.value,
            'subject': t.title,
            'status_label': t.status.value,
            'status_class': _ticket_status_class(t.status.value),
            'view_url': url_for('tickets.view_ticket', ticket_uid=t.uid_public),
        })

    for sub in FormSubmission.query.filter_by(author_id=user.id).all():
        if sub.get_ticket_ids():
            continue  # déjà représentée via ses tickets ci-dessus
        subject = sub.form.name if sub.form else 'Formulaire'
        if search_query:
            q = search_query.lower()
            if q not in sub.uid_public.lower() and q not in subject.lower():
                continue
        if sub.status == FormSubmissionStatus.REFUSED:
            status_label, status_class = 'REFUSÉ', 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-300'
        elif sub.status == FormSubmissionStatus.DONE:
            status_label, status_class = 'TERMINÉ', 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
        else:
            status_label, status_class = 'EN ATTENTE DE VALIDATION', 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300'
        items.append({
            'ref': sub.uid_public,
            'date': sub.created_at,
            'service': subject,
            'subject': subject,
            'status_label': status_label,
            'status_class': status_class,
            'view_url': url_for('forms.view_submission', id=sub.id),
        })

    items.sort(key=lambda i: i['date'], reverse=True)
    return items


@main_bp.route('/my_history')
@login_required
def my_history():
    search_query = request.args.get('q', '')
    items = _user_history_items(current_user, search_query)
    return render_template('my_history.html', items=items, search_query=search_query)

@main_bp.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    return render_template(
        'admin_hub.html',
        users_count=User.query.count(),
        forms_count=FormDefinition.query.count(),
        active_forms_count=FormDefinition.query.filter_by(is_active=True).count(),
    )

@main_bp.route('/dashboard')
@login_required
def dashboard():
    # Redirection intelligente selon le rôle
    role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    
    if 'ADMIN' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    elif 'MANAGER' in role or 'DIRECTEUR' in role:
        return redirect(url_for('tickets.manager_dashboard'))
    elif 'SOLVER' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    
    return redirect(url_for('main.user_portal'))

@main_bp.route('/help')
@login_required
def help_center():
    return render_template('help.html')

@main_bp.route('/docs/circuits-validation')
@login_required
def doc_circuits_validation():
    # Fichier HTML autonome (pas un template Jinja) — servi directement,
    # protégé par @login_required contrairement à /static qui est exposé
    # sans authentification par nginx (alias direct, hors Flask).
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs')
    return send_from_directory(docs_dir, 'circuits-validation.html')

@main_bp.route('/health')
def health():
    """Sonde de disponibilité publique (sans authentification, pour rester
    utilisable même si le login est en panne) — utilisée par le watchdog
    externe (scripts/watchdog.sh) et tout supervision future."""
    data = get_liveness()
    code = 200 if data['status'] == 'ok' else 503
    return jsonify(data), code

@main_bp.route('/admin/health')
@login_required
@admin_required
def admin_health():
    return render_template('admin_health.html')

@main_bp.route('/admin/health/data')
@login_required
@admin_required
def admin_health_data():
    return jsonify(get_full_health())

@main_bp.route('/profile')
@login_required
def profile():
    """Page profil complète : Mon compte / Apparence / Signaler un bug (onglets
    Alpine, l'onglet initial vient de ?tab=). Le panneau latéral de base.html
    n'est plus qu'un raccourci vers cette page."""
    tab = request.args.get('tab', 'account')
    if tab not in ('account', 'appearance', 'bug'):
        tab = 'account'

    items = _user_history_items(current_user)
    stats = {
        'total': len(items),
        'open': sum(1 for i in items if i['status_label'] not in ('TERMINE', 'TERMINÉ', 'REFUSE', 'REFUSÉ')),
        'done': sum(1 for i in items if i['status_label'] in ('TERMINE', 'TERMINÉ')),
        'last': items[0]['date'] if items else None,
    }
    # Nom / prénom dérivés du fullname LDAP ("Prénom NOM" dans l'annuaire ILVM).
    parts = (current_user.fullname or '').split(' ', 1)
    if len(parts) > 1:
        first_name, last_name = parts
    else:
        first_name, last_name = '', parts[0]  # nom d'affichage sans espace (comptes techniques)

    return render_template(
        'profile.html',
        active_tab=tab,
        stats=stats,
        recent_items=items[:5],
        first_name=first_name,
        last_name=last_name,
        palette=PROFILE_THEME_PALETTE,
        bug_types=PROFILE_BUG_TYPES,
        bug_page=request.args.get('page', ''),
    )

@main_bp.route('/profile/info', methods=['POST'])
@login_required
def profile_info_update():
    """Coordonnées éditables (téléphone, bureau) + initiales personnalisées."""
    current_user.phone = request.form.get('phone', '').strip()[:30] or None
    current_user.office = request.form.get('office', '').strip()[:100] or None

    # Initiales personnalisées : ignorées si une photo est déjà définie (la
    # photo prime toujours sur les initiales tant qu'elle existe).
    initials = request.form.get('avatar_initials', '').strip().upper()
    if not current_user.avatar_photo:
        current_user.avatar_initials = initials[:2] or None

    db.session.commit()
    flash('Profil mis à jour.', 'success')
    return redirect(url_for('main.profile', tab='account'))

@main_bp.route('/profile/appearance', methods=['POST'])
@login_required
def profile_appearance_update():
    """Préférences d'apparence. Accepte du JSON (aperçu en direct depuis la
    page profil / bascule clair-sombre de l'en-tête) ou un POST de formulaire
    classique. Chaque champ est optionnel et validé contre sa whitelist ;
    une valeur inconnue est simplement ignorée."""
    data = request.get_json(silent=True) or request.form
    changed = {}

    color = (data.get('theme_color') or '').strip().lower()
    if color in PROFILE_THEME_COLORS:
        current_user.theme_color = color; changed['theme_color'] = color
    mode = (data.get('theme_mode') or '').strip().lower()
    if mode in PROFILE_THEME_MODES:
        current_user.theme_mode = mode; changed['theme_mode'] = mode
    scale = (data.get('font_scale') or '').strip().lower()
    if scale in PROFILE_FONT_SCALES:
        current_user.font_scale = scale; changed['font_scale'] = scale
    density = (data.get('density') or '').strip().lower()
    if density in PROFILE_DENSITIES:
        current_user.density = density; changed['density'] = density
    if 'high_contrast' in data:
        raw = data.get('high_contrast')
        hc = raw if isinstance(raw, bool) else str(raw).lower() in ('1', 'true', 'on', 'yes')
        current_user.high_contrast = hc; changed['high_contrast'] = hc

    db.session.commit()
    if request.is_json:
        return jsonify({'ok': True, 'changed': changed})
    flash('Apparence enregistrée.', 'success')
    return redirect(url_for('main.profile', tab='appearance'))

@main_bp.route('/profile/bug', methods=['POST'])
@login_required
def profile_bug():
    """Déclaration d'un bug sur l'intranet : crée un Ticket standard vers
    l'Informatique (catégorie "Bug Intranet", statut PENDING — aucune étape de
    validation hiérarchique, un bug ne se valide pas), puis notifie les
    solvers Informatique exactement comme n'importe quel nouveau ticket
    (cloche in-app + email). Le déclarant retrouve le ticket dans son
    historique et peut échanger via le chat du ticket."""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    bug_type = request.form.get('bug_type', '').strip()
    page = request.form.get('page', '').strip()
    user_agent = request.form.get('user_agent', '').strip() or request.headers.get('User-Agent', '')
    screen = request.form.get('screen', '').strip()

    if not title or not description:
        flash('Le titre et la description sont obligatoires.', 'danger')
        return redirect(url_for('main.profile', tab='bug'))
    if bug_type not in PROFILE_BUG_TYPES:
        bug_type = PROFILE_BUG_TYPES[0]

    full_description = (
        f"Type : {bug_type}\n"
        f"Page concernée : {page or 'non précisée'}\n\n"
        f"{description}\n\n"
        f"--- Informations techniques (collectées automatiquement) ---\n"
        f"Navigateur : {user_agent or 'inconnu'}\n"
        f"Résolution : {screen or 'inconnue'}"
    )

    uid = generate_ticket_uid()

    # Capture d'écran optionnelle, stockée comme les captures du flux ticket
    # historique (uploads/tickets/<uid>/CAPTURE_*, référencée dans daf_files_json).
    files = []
    shot = request.files.get('screenshot')
    if shot and shot.filename:
        ext = shot.filename.rsplit('.', 1)[-1].lower() if '.' in shot.filename else ''
        if ext in PROFILE_PHOTO_EXTENSIONS:
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', uid)
            fname = secure_filename(f"CAPTURE_{shot.filename}")
            try:
                os.makedirs(upload_path, exist_ok=True)
                shot.save(os.path.join(upload_path, fname))
                files.append(fname)
            except Exception as e:
                current_app.logger.warning(f"Bug intranet {uid} : capture non enregistrée ({e})")
        else:
            flash('Capture ignorée : format non supporté (PNG, JPG ou WEBP).', 'warning')

    t = Ticket(
        title=f"[Bug Intranet] {title}",
        description=full_description,
        author=current_user,
        target_service=ServiceType.INFO,
        status=TicketStatus.PENDING,
        uid_public=uid,
        category_ticket='Bug Intranet',
        created_at=get_paris_time(),
        service_demandeur=current_user.service,
        tel_demandeur=current_user.phone,
        daf_files_json=json.dumps(files),
    )
    try:
        db.session.add(t)
        db.session.flush()
        notify_solvers_new_ticket(t)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de l'enregistrement du signalement : {e}", 'danger')
        return redirect(url_for('main.profile', tab='bug'))

    recipients = get_service_emails(ServiceType.INFO)
    if recipients:
        send_service_alert(t, recipients)

    flash(f'Merci ! Votre signalement {uid} a été transmis au service Informatique.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_uid=uid))

@main_bp.route('/profile/photo', methods=['POST'])
@login_required
def profile_photo_upload():
    file = request.files.get('photo')
    if not file or not file.filename:
        flash('Aucune image sélectionnée.', 'danger')
        return redirect(url_for('main.profile', tab='account'))

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in PROFILE_PHOTO_EXTENSIONS:
        flash('Format d\'image non supporté (PNG, JPG ou WEBP uniquement).', 'danger')
        return redirect(url_for('main.profile', tab='account'))

    avatars_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars')
    os.makedirs(avatars_dir, exist_ok=True)

    # Supprime l'ancienne photo si elle avait une extension différente,
    # pour ne pas accumuler de fichiers orphelins au fil des changements.
    if current_user.avatar_photo:
        old_path = os.path.join(avatars_dir, current_user.avatar_photo)
        if os.path.exists(old_path):
            try: os.remove(old_path)
            except OSError: pass

    filename = secure_filename(f'user_{current_user.id}.{ext}')
    file.save(os.path.join(avatars_dir, filename))
    current_user.avatar_photo = filename
    db.session.commit()
    flash('Photo de profil mise à jour.', 'success')
    return redirect(url_for('main.profile', tab='account'))

@main_bp.route('/profile/photo/delete', methods=['POST'])
@login_required
def profile_photo_delete():
    if current_user.avatar_photo:
        avatars_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars')
        old_path = os.path.join(avatars_dir, current_user.avatar_photo)
        if os.path.exists(old_path):
            try: os.remove(old_path)
            except OSError: pass
        current_user.avatar_photo = None
        db.session.commit()
        flash('Photo de profil supprimée.', 'success')
    return redirect(url_for('main.profile', tab='account'))
