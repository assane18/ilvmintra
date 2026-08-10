import os
import io
import ldap
from datetime import datetime
from flask import render_template, request, jsonify, current_app, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from . import tech

# ==============================================================================
# CONFIGURATION
# ==============================================================================
FICHE_SAVE_DIR = '/mnt/ilvmfap1_info/INVENTAIRE DU PARC/Materiels/Historique des remises tel+pc/Fiche pret Generé'

LDAP_SERVER   = 'ldap://192.168.1.9'
LDAP_BASE_DN  = 'DC=ilvm,DC=lan'
LDAP_USER     = 'CN=Admin Intra,CN=Users,DC=ilvm,DC=lan'
LDAP_PASSWORD = 'gq!nsXPYsM!LmFh4'

# ==============================================================================
# HELPERS
# ==============================================================================

def _check_info_access():
    user_role    = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    user_services = current_user.get_allowed_services()
    return 'ADMIN' in user_role or 'INFORMATIQUE' in user_services or 'INFO' in user_services


def _parse_date(s):
    """Parse DD/MM/YYYY → datetime, retourne None si vide."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), '%d/%m/%Y')
    except ValueError:
        return None


# ==============================================================================
# ROUTES
# ==============================================================================

@tech.route('/generateur')
@login_required
def home():
    if not _check_info_access():
        flash("Accès réservé au service Informatique.", "danger")
        return redirect(url_for('main.user_portal'))
    return render_template('tech/generateur_pret.html')


@tech.route('/generer_fiche', methods=['POST'])
@login_required
def generer_fiche():
    if not _check_info_access():
        return jsonify({'error': 'Accès refusé'}), 403

    from .pdf_pret import generate_fiche_pret
    from app.models import Materiel, Pret, db
    import io as _io

    data      = request.get_json(force=True)
    logo_path = os.path.join(current_app.root_path, 'static', 'img', 'logo-pdf.png')

    try:
        pdf_bytes = generate_fiche_pret(data, logo_path)
        nom_complet = (data.get('nom') or 'Agent').strip()
        sn          = (data.get('sn')  or 'SN').strip()
        filename    = f"FichePret_{nom_complet.replace(' ', '_')}_{sn}.pdf"

        # ── Sauvegarde réseau ────────────────────────────────────────
        try:
            if os.path.isdir(FICHE_SAVE_DIR):
                with open(os.path.join(FICHE_SAVE_DIR, filename), 'wb') as f:
                    f.write(pdf_bytes)
        except Exception as e:
            print(f"--- WARN réseau : {e}")

        # ── Enregistrement du prêt en base ──────────────────────────
        try:
            materiel = Materiel.query.filter_by(sn=sn).first()

            # Créer le matériel s'il n'existe pas encore (saisie manuelle)
            if not materiel:
                materiel = Materiel(
                    categorie=data.get('type_mat') or 'Autre',
                    modele=data.get('modele') or '',
                    sn=sn,
                    imei=data.get('imei') or '',
                    statut='En prêt'
                )
                db.session.add(materiel)
                db.session.flush()
            else:
                materiel.statut = 'En prêt'

            # Découpage nom / prénom (ex: "DUPONT Jean" → nom=DUPONT prenom=Jean)
            parts = nom_complet.split(' ', 1)
            nom_emp    = parts[0]
            prenom_emp = parts[1] if len(parts) > 1 else ''

            pret = Pret(
                materiel_id        = materiel.id,
                technicien_id      = current_user.id,
                nom_emprunteur     = nom_emp,
                prenom_emprunteur  = prenom_emp,
                service_emprunteur = data.get('service') or '',
                date_sortie        = _parse_date(data.get('date_depart')) or datetime.utcnow(),
                date_retour_prevue = _parse_date(data.get('date_retour')),
                statut_dossier     = 'En cours',
                type_pret          = data.get('type_pret') or '',
                accessoires        = ', '.join(data.get('accessoires') or []),
                etat_ecran_sortie  = data.get('etat_ecran')  or 'Bon',
                etat_clavier_sortie= data.get('etat_clavier') or 'Bon',
                etat_coque_sortie  = data.get('etat_coque')  or 'Bon',
            )
            db.session.add(pret)
            db.session.commit()
            print(f"--- INFO: Prêt #{pret.id} créé pour {nom_complet} — {sn}")
        except Exception as db_err:
            db.session.rollback()
            print(f"--- WARN DB prêt : {db_err}")

        return send_file(
            _io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tech.route('/get_inventory')
@login_required
def get_inventory():
    """Retourne l'inventaire depuis la base de données (matériels disponibles)."""
    from app.models import Materiel
    try:
        materiels = Materiel.query.order_by(Materiel.modele).all()
        data = []
        for m in materiels:
            data.append({
                'SN':     m.sn     or '',
                'Modele': m.modele or '',
                'Type':   m.categorie or '',
                'IMEI':   m.imei   or '',
                'Statut': m.statut or '',
            })
        return jsonify(data)
    except Exception as e:
        print(f"--- ERROR get_inventory DB : {e}")
        return jsonify([])


@tech.route('/upload_inventory', methods=['POST'])
@login_required
def upload_inventory():
    """Importe un fichier Excel dans la base de données (table materiels)."""
    if not _check_info_access():
        return jsonify({"success": False, "message": "Accès refusé"})

    from app.models import Materiel, db

    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Aucun fichier reçu"})

    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({"success": False, "message": "Format invalide (.xlsx requis)"})

    try:
        wb = load_workbook(file, data_only=True)
        ws = wb.active

        # Normalisation des en-têtes
        raw_headers = [str(c.value or '').upper().strip() for c in ws[1]]
        def find_col(keywords):
            for kw in keywords:
                for i, h in enumerate(raw_headers):
                    if kw in h:
                        return i
            return None

        idx_sn       = find_col(['SERIE', 'SERIAL', 'S/N', 'SN'])
        idx_cat      = find_col(['TYPE', 'CATEGORIE', 'CATEG'])
        idx_modele   = find_col(['MODEL', 'MODELE', 'MARQUE'])
        idx_hostname = find_col(['HOST', 'NOM'])
        idx_imei     = find_col(['IMEI'])

        if idx_sn is None:
            return jsonify({"success": False, "message": "Colonne SN introuvable dans le fichier"})

        added = skipped = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            def cell(idx):
                if idx is None or idx >= len(row):
                    return ''
                v = row[idx]
                s = str(v).strip() if v is not None else ''
                return s[:-2] if s.endswith('.0') else s

            sn = cell(idx_sn)
            if not sn:
                continue
            if Materiel.query.filter_by(sn=sn).first():
                skipped += 1
                continue

            m = Materiel(
                sn        = sn,
                categorie = cell(idx_cat)      or 'Autre',
                modele    = cell(idx_modele)   or 'Inconnu',
                hostname  = cell(idx_hostname) or '',
                imei      = cell(idx_imei)     or '',
                statut    = 'Disponible',
            )
            db.session.add(m)
            added += 1

        db.session.commit()
        return jsonify({"success": True,
                        "message": f"{added} article(s) importé(s), {skipped} déjà existant(s)."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})


@tech.route('/download_template')
@login_required
def download_template():
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventaire"

    headers     = ['Type', 'Modele', 'SN', 'Hostname', 'IMEI']
    header_fill = PatternFill(start_color="0056B3", end_color="0056B3", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    examples = [
        ['Ordinateur portable', 'Dell Latitude 5540',  'SN-EXEMPLE-001', 'PC-EXEMPLE-01', ''],
        ['Tablette',            'Samsung Galaxy Tab A8','SN-EXEMPLE-002', '',              '351234567890123'],
        ['Téléphone portable',  'Apple iPhone 13',      'SN-EXEMPLE-003', '',              '352345678901234'],
    ]
    for row_data in examples:
        ws.append(row_data)

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='Inventaire_Exemple.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@tech.route('/get_user/<username>')
def get_user(username):
    try:
        l = ldap.initialize(LDAP_SERVER)
        l.protocol_version = ldap.VERSION3
        l.set_option(ldap.OPT_REFERRALS, 0)
        try:
            l.simple_bind_s(LDAP_USER, LDAP_PASSWORD)
        except ldap.INVALID_CREDENTIALS:
            return jsonify({"success": False, "message": "Erreur Auth LDAP"})
        except Exception as e:
            return jsonify({"success": False, "message": f"Erreur connexion : {e}"})

        result = l.search_s(LDAP_BASE_DN, ldap.SCOPE_SUBTREE,
                            f"(sAMAccountName={username})",
                            ['displayName', 'mail', 'department', 'telephoneNumber'])

        if result and result[0][1]:
            u = result[0][1]
            def dec(k):
                v = u.get(k, [b''])
                return v[0].decode('utf-8', errors='ignore') if v else ''
            return jsonify({"success": True, "nom": dec('displayName'),
                            "mail": dec('mail'), "service": dec('department'),
                            "telephone": dec('telephoneNumber')})
        return jsonify({"success": False, "message": "Utilisateur introuvable"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
