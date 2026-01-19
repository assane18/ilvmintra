from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, UserRole, ServiceType
from app import db
from ldap3 import Server, Connection, ALL, SIMPLE
from functools import wraps
from sqlalchemy.exc import DataError, StatementError
import unicodedata

auth_bp = Blueprint('auth', __name__)

# --- ANTI-CACHE RENFORCÉ ---
def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return no_cache

def normalize_text(text):
    """Supprime les accents et met en majuscules pour la comparaison"""
    if not text: return ""
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')
    return text.upper().replace(' ', '_').replace('-', '_')

def get_ldap_connection(username, password):
    LDAP_SERVER_URL = current_app.config.get('LDAP_SERVER', 'ldap://192.168.1.9') 
    LDAP_DOMAIN_PREFIX = current_app.config.get('LDAP_DOMAIN', 'ILVM\\') 
    LDAP_BASE_DN = current_app.config.get('LDAP_BASE_DN', 'dc=ilvm,dc=lan')
    
    try:
        server = Server(LDAP_SERVER_URL, get_info=ALL, connect_timeout=5)
        clean_username = username.split('@')[0].split('\\')[-1]
        user_dn = f"{LDAP_DOMAIN_PREFIX}{clean_username}"
        conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE, auto_bind=True)
        return conn, LDAP_BASE_DN, None
    except Exception as e:
        return None, None, str(e)

def parse_ad_groups(groups_entry):
    # On met tout en MAJUSCULES pour simplifier les comparaisons
    groups_list = [str(g).upper().split(',')[0].replace('CN=', '') for g in groups_entry]
    role = UserRole.USER
    origin_services = []
    allowed_services = []

    for group in groups_list:
        # 1. RÔLES (GR-)
        if group.startswith('GR-'):
            role_suffix = group.replace('GR-', '')
            if role_suffix == 'DIRECTEUR': role = UserRole.DIRECTEUR
            elif role_suffix == 'MANAGER' and role != UserRole.DIRECTEUR: role = UserRole.MANAGER
            elif role_suffix == 'SOLVER' and role != UserRole.DIRECTEUR and role != UserRole.MANAGER: role = UserRole.SOLVER
            elif role_suffix == 'ADMIN': role = UserRole.ADMIN

        # 2. SERVICES GÉRÉS (GS-)
        elif group.startswith('GS-'):
            svc_name = group.replace('GS-', '') # ex: 'SESSAD CRETEIL' ou 'INFORMATIQUE'
            
            # --- MAPPING MANUEL COMPLET ---
            # Services Historiques / Techniques
            if svc_name in ['INFORMATIQUE', 'INFO']: allowed_services.append(ServiceType.INFO.value)
            elif svc_name == 'DAF': allowed_services.append(ServiceType.DAF.value)
            elif svc_name in ['TECHNIQUE', 'TECH']: allowed_services.append(ServiceType.TECH.value)
            elif svc_name in ['GENERAUX', 'GEN']: allowed_services.append(ServiceType.GEN.value)
            elif svc_name == 'DRH': allowed_services.append(ServiceType.DRH.value)
            elif svc_name == 'SECU': allowed_services.append(ServiceType.SECU.value)
            
            # Services Ajoutés (Mapping explicite pour éviter les erreurs de syntaxe AD)
            elif svc_name == 'ACCUEIL': allowed_services.append(ServiceType.ACCUEIL.value)
            elif svc_name == 'ARCHIPELLE': allowed_services.append(ServiceType.ARCHIPELLE.value)
            elif svc_name == 'CELLULE PARCOURS': allowed_services.append(ServiceType.CELLULE_PARCOURS.value)
            elif svc_name == 'CSD': allowed_services.append(ServiceType.CSD.value)
            elif svc_name == 'DG': allowed_services.append(ServiceType.DG.value)
            elif svc_name == 'EAM DRAVEIL': allowed_services.append(ServiceType.EAM_DRAVEIL.value)
            elif svc_name == 'ESAT': allowed_services.append(ServiceType.ESAT.value)
            elif svc_name == 'ESPACE LOISIRS': allowed_services.append(ServiceType.ESPACE_LOISIRS.value)
            elif svc_name == 'FH': allowed_services.append(ServiceType.FH.value)
            elif svc_name == 'FJ': allowed_services.append(ServiceType.FJ.value)
            elif svc_name == 'FV': allowed_services.append(ServiceType.FV.value)
            elif svc_name == 'GITE': allowed_services.append(ServiceType.GITE.value)
            elif svc_name == 'IME CORBEIL': allowed_services.append(ServiceType.IME_CORBEIL.value)
            elif svc_name == 'MAGASIN': allowed_services.append(ServiceType.MAGASIN.value)
            elif svc_name == 'MAS': allowed_services.append(ServiceType.MAS.value)
            elif svc_name == 'MAS EXTERNAT': allowed_services.append(ServiceType.MAS_EXTERNAT.value)
            elif svc_name == 'MAS INCLUSIVE': allowed_services.append(ServiceType.MAS_INCLUSIVE.value)
            elif svc_name == 'PATRIMOINE': allowed_services.append(ServiceType.PATRIMOINE.value)
            elif svc_name == 'QUALITE': allowed_services.append(ServiceType.QUALITE.value)
            elif svc_name == 'SACAT': allowed_services.append(ServiceType.SACAT.value)
            elif svc_name == 'SAMSAH': allowed_services.append(ServiceType.SAMSAH.value)
            elif svc_name == 'SAVIE': allowed_services.append(ServiceType.SAVIE.value)
            elif svc_name == 'SECURITE INCENDIE': allowed_services.append(ServiceType.SECURITE_INCENDIE.value)
            elif svc_name == 'SESSAD CORBEIL': allowed_services.append(ServiceType.SESSAD_CORBEIL.value)
            elif svc_name == 'SESSAD CRETEIL': allowed_services.append(ServiceType.SESSAD_CRETEIL.value)
            elif svc_name == 'SESSAD TSA': allowed_services.append(ServiceType.SESSAD_TSA.value)
            elif svc_name == 'SG': allowed_services.append(ServiceType.SG.value)
            elif svc_name == 'SRU': allowed_services.append(ServiceType.SRU.value)
            elif svc_name == 'SYNDICAT': allowed_services.append(ServiceType.SYNDICAT.value)
            elif svc_name == 'TKITOI': allowed_services.append(ServiceType.TKITOI.value)
            elif svc_name == 'UEEA': allowed_services.append(ServiceType.UEEA.value)
            elif svc_name == 'UEMA': allowed_services.append(ServiceType.UEMA.value)
            
            # Fallback (Au cas où un nouveau service arrive sans mapping)
            else:
                allowed_services.append(svc_name)

        # 3. SERVICES D'ORIGINE (GU-)
        elif group.startswith('GU-'):
            origin_services.append(group.replace('GU-', ''))

    if role == UserRole.SOLVER and not allowed_services: role = UserRole.USER
    return role, origin_services, allowed_services

@auth_bp.route('/login', methods=['GET', 'POST'])
@nocache 
def login():
    if current_user.is_authenticated:
        return redirect_by_role(current_user)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn, base_dn, error_msg = get_ldap_connection(username, password)
        
        if conn:
            try:
                clean_user = username.split('@')[0].split('\\')[-1]
                search_filter = f'(sAMAccountName={clean_user})'
                conn.search(base_dn, search_filter, attributes=['memberOf', 'displayName', 'mail'])
                
                if not conn.entries:
                    flash("Utilisateur introuvable.", "warning")
                    return render_template('auth/login.html')
                    
                user_entry = conn.entries[0]
                role, origins, alloweds = parse_ad_groups(user_entry.memberOf)
                
                user = User.query.filter_by(username=clean_user).first()
                if not user:
                    user = User(username=clean_user)
                    db.session.add(user)
                
                user.fullname = str(user_entry.displayName) if user_entry.displayName else clean_user
                user.email = str(user_entry.mail) if user_entry.mail else f"{clean_user}@ilvm.lan"
                
                # Mise à jour des droits
                user.role = role
                user.set_origin_services(origins)
                user.set_allowed_services(alloweds)
                
                if clean_user.lower() == 'administrateur': user.role = UserRole.ADMIN
                
                try:
                    db.session.commit()
                except (DataError, StatementError) as db_err:
                    db.session.rollback()
                    flash(f"Erreur Base de Données (Enum) : {db_err}", "danger")
                    print(f"ERREUR BDD: {db_err}")
                    return render_template('auth/login.html')

                login_user(user)
                return redirect_by_role(user)
                
            except Exception as e:
                flash(f"Erreur technique : {e}", "danger")
                print(f"ERREUR CONNEXION: {e}")
        else:
            flash(f"Échec connexion : {error_msg}", "danger")

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
@nocache
def logout():
    session.clear()
    logout_user()
    flash("Déconnecté.", "info")
    return redirect(url_for('auth.login'))

def redirect_by_role(user):
    role = str(user.role.value).upper() if hasattr(user.role, 'value') else str(user.role).upper()
    if 'ADMIN' in role: return redirect(url_for('tickets.solver_dashboard'))
    if 'DIRECTEUR' in role or 'MANAGER' in role: return redirect(url_for('tickets.manager_dashboard'))
    if 'SOLVER' in role: return redirect(url_for('tickets.solver_dashboard'))
    return redirect(url_for('main.user_portal'))
