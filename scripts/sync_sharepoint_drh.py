#!/var/www/intranet/venv/bin/python3
"""Synchronise les réponses du formulaire DRH externe (Val Connect, Microsoft
Forms) vers le pool de tickets de l'Espace Tech.

Le formulaire externe exporte ses réponses en direct dans un classeur Excel
(Forms -> "Ouvrir dans Excel"), stocké dans le OneDrive du propriétaire du
formulaire (comportement fixe de Microsoft Forms — voir mémoire projet
sharepoint_drh_integration pour le contexte complet : pas de moyen natif de
rediriger cet export vers Val Connect car ce site n'a pas de groupe
Microsoft 365 associé). Ce script lit ce classeur via Microsoft Graph
(authentification app-only, app Entra ID "Intranet-Sync-DRH",
Files.Read.All) et crée un Ticket par destinataire DRH dont la condition
est satisfaite, en reproduisant fidèlement le dispatch du formulaire DRH
interne (drh-v2) : toujours un ticket pour DRH générique, plus un ticket par
sous-service (PAIE_CARRIERE, RECRUTEMENT_FORMATION, EFFECTIFS_SOCIAL) dont
la liste de types de demande couvre celui de la réponse. Idempotent : relit
toutes les lignes à chaque exécution mais ne recrée jamais un ticket dont
l'uid_public existe déjà.

Le champ "Capture d'écran / Photo" (upload de fichier) est rapatrié : la
cellule contient le webUrl complet du fichier stocké par Forms dans le
OneDrive du propriétaire (ex: .../Documents/Applications/Microsoft
Forms/Demande DRH 1/Question/logo_Untel.png — le nom de sous-dossier
"Question" est un artefact du nom du champ au moment de sa création dans
Forms, pas garanti stable — d'où l'extraction du chemin depuis l'URL
elle-même plutôt qu'un chemin recodé en dur). Le fichier est copié
physiquement dans app/static/uploads/tickets/{uid}/ pour chaque ticket créé
à partir de cette réponse, exactement comme le fait le moteur de formulaires
interne (app/routes/forms.py::_create_one_ticket), et référencé via
Ticket.daf_files_json pour que le template de détail du ticket l'affiche.

Usage cron (toutes les 5 min) :
  */5 * * * * /var/www/intranet/scripts/sync_sharepoint_drh.py >> /var/www/intranet/backups/sync_sharepoint_drh.log 2>&1
"""
import os
import sys
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote, quote

import msal
import requests

sys.path.insert(0, '/var/www/intranet')

from app import create_app, db  # noqa: E402
from app.models import (  # noqa: E402
    Ticket, TicketStatus, ServiceType, User, UserRole,
    FormDefinition, FormDispatchTarget,
)
from app.emails import send_service_alert  # noqa: E402

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
EXCEL_EPOCH = datetime(1899, 12, 30)  # epoch des dates Excel (avec le bug de l'an 1900)


def get_graph_token():
    tenant_id = os.environ['AZURE_TENANT_ID']
    client_id = os.environ['AZURE_CLIENT_ID']
    client_secret = os.environ['AZURE_CLIENT_SECRET']
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            f"Authentification Graph échouée : {result.get('error')} — {result.get('error_description')}"
        )
    return result["access_token"]


def find_excel_item_id(headers, owner_upn, filename):
    """Cherche le fichier par nom à la racine du OneDrive du propriétaire
    (pas de recherche via /search, qui renvoie 403 avec Files.Read.All seul —
    lister root/children suffit, le volume de fichiers y est faible)."""
    r = requests.get(f"{GRAPH_BASE}/users/{owner_upn}/drive/root/children", headers=headers)
    r.raise_for_status()
    for item in r.json().get("value", []):
        if item.get("name") == filename:
            return item["id"]
    raise RuntimeError(f"Fichier '{filename}' introuvable dans le OneDrive de {owner_upn}.")


def get_excel_rows(headers, owner_upn, item_id):
    """Retourne les lignes du (premier et unique) tableau du classeur, sous
    forme de dicts {nom_de_colonne: valeur}."""
    r = requests.get(
        f"{GRAPH_BASE}/users/{owner_upn}/drive/items/{item_id}/workbook/tables",
        headers=headers,
    )
    r.raise_for_status()
    tables = r.json().get("value", [])
    if not tables:
        return []
    table_id = tables[0]["id"]

    r = requests.get(
        f"{GRAPH_BASE}/users/{owner_upn}/drive/items/{item_id}/workbook/tables/{table_id}/columns",
        headers=headers,
    )
    r.raise_for_status()
    columns = sorted(r.json().get("value", []), key=lambda c: c["index"])
    column_names = [c["name"] for c in columns]

    r = requests.get(
        f"{GRAPH_BASE}/users/{owner_upn}/drive/items/{item_id}/workbook/tables/{table_id}/rows",
        headers=headers,
    )
    r.raise_for_status()
    rows = []
    for row in r.json().get("value", []):
        values = row["values"][0]
        rows.append(dict(zip(column_names, values)))
    return rows


def excel_serial_to_datetime(value):
    if not value:
        return datetime.utcnow()
    try:
        return EXCEL_EPOCH + timedelta(days=float(value))
    except (TypeError, ValueError):
        return datetime.utcnow()


def get_drh_dispatch_targets():
    """Recharge les destinataires DRH (et leurs conditions) depuis la
    définition du formulaire interne drh-v2, pour rester automatiquement
    synchronisé si leur configuration change côté admin des formulaires —
    pas de valeurs recopiées en dur ici."""
    form_def = FormDefinition.query.filter_by(slug='drh-v2').first()
    if not form_def:
        raise RuntimeError("FormDefinition 'drh-v2' introuvable — impossible de déterminer le dispatch DRH.")
    return list(form_def.dispatch_targets)


def targets_for_type_demande(targets, type_demande):
    """Une cible sans condition (le DRH générique) s'applique toujours ; les
    autres s'appliquent si type_demande fait partie de leurs valeurs
    autorisées — même logique que FormDispatchTarget.is_satisfied côté
    moteur de formulaires interne, réécrite ici pour ne dépendre que de
    condition_values_json (le seul type de condition utilisé par drh-v2)."""
    matched = []
    for target in targets:
        if not target.condition_field_id:
            matched.append(target)
            continue
        values = target.get_condition_values() if hasattr(target, 'get_condition_values') else []
        if type_demande in values:
            matched.append(target)
    return matched


def download_attachment(headers, owner_upn, file_url):
    """Le lien stocké dans la cellule "Capture d'écran / Photo" est le webUrl
    OneDrive du fichier (.../Documents/{chemin relatif}) — on extrait ce
    chemin plutôt que de deviner le nom du sous-dossier Forms (qui dépend du
    nom du champ au moment de sa création, pas garanti stable), puis on
    résout l'item par chemin et on télécharge son contenu. Retourne
    (nom_de_fichier, contenu_binaire) ou (None, None) si l'URL est
    inexploitable."""
    if not file_url:
        return None, None
    path = unquote(urlparse(file_url).path)
    marker = '/Documents/'
    idx = path.find(marker)
    if idx == -1:
        print(f"  Attention : impossible d'extraire le chemin OneDrive depuis {file_url!r}.")
        return None, None
    relative_path = path[idx + len(marker):]

    r = requests.get(
        f"{GRAPH_BASE}/users/{owner_upn}/drive/root:/{quote(relative_path)}",
        headers=headers,
    )
    if r.status_code != 200:
        print(f"  Attention : fichier introuvable via Graph pour {relative_path!r} ({r.status_code}).")
        return None, None
    item = r.json()

    content_r = requests.get(
        f"{GRAPH_BASE}/users/{owner_upn}/drive/items/{item['id']}/content",
        headers=headers,
    )
    content_r.raise_for_status()
    return item['name'], content_r.content


def attach_file_to_ticket(ticket, filename, content):
    """Copie le fichier dans app/static/uploads/tickets/{uid}/ et met à jour
    Ticket.daf_files_json — même convention que
    app/routes/forms.py::_create_one_ticket (le champ s'appelle daf_files_json
    pour des raisons historiques mais sert de liste générique de fichiers
    joints à un ticket, pas seulement pour le module DAF)."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    filename = secure_filename(filename) or 'piece_jointe'
    base = os.path.join(current_app.root_path, 'static', 'uploads', 'tickets', ticket.uid_public)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, filename), 'wb') as f:
        f.write(content)
    ticket.daf_files_json = json.dumps([filename])


def find_author(email):
    if not email:
        return None
    return User.query.filter(User.email.ilike(email)).first()


def build_description(row):
    lines = []
    # Le titre n'est demandé que pour le type "Autre" (embranchement Forms) :
    # vide pour les autres types, inutile d'afficher une ligne "-".
    if row.get('Titre de la demande'):
        lines.append(f"Titre de la demande : {row['Titre de la demande']}")
    lines += [
        f"Description détaillée : {row.get('Description détaillée') or '-'}",
        f"Téléphone de contact : {row.get('Téléphone de contact') or '-'}",
        f"Soumis via le formulaire externe (Val Connect) par {row.get('Nom') or '-'} ({row.get('Adresse de messagerie') or '-'}).",
    ]
    return "\n".join(lines)


def notify_solvers_new_ticket(ticket):
    """Reproduit app/routes/tickets.py::notify_solvers_new_ticket — dupliqué
    ici pour ne pas dépendre d'un import de tickets.py (module volumineux
    couplé à Flask-Login/current_user, non pensé pour être importé depuis un
    script), même principe que scripts/relance_tickets.py.

    Lien construit manuellement (BASE_URL + chemin) plutôt que via url_for :
    ce script tourne hors contexte de requête HTTP (pas de SERVER_NAME), donc
    url_for lève RuntimeError ici — même contournement que send_service_alert
    dans app/emails.py."""
    from app.models import Notification
    from flask import current_app
    link = current_app.config.get('BASE_URL', '').rstrip('/') + '/tickets/solver/dashboard'
    service_enum = ticket.target_service
    solvers = User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.ADMIN])).all()
    for s in solvers:
        if s.role == UserRole.ADMIN:
            db.session.add(Notification(
                user=s, message=f"Nouveau ticket : {ticket.uid_public}",
                category='info', link=link,
            ))
            continue
        allowed = s.get_allowed_services()
        target_str = str(service_enum.value) if hasattr(service_enum, 'value') else str(service_enum)
        if target_str in allowed or service_enum.name in allowed:
            db.session.add(Notification(
                user=s, message=f"Nouveau ticket : {ticket.uid_public}",
                category='info', link=link,
            ))


def get_service_emails(service_enum):
    """Reproduit app/routes/tickets.py::get_service_emails — même principe
    de duplication que ci-dessus."""
    staff = User.query.filter(User.role.in_(
        [UserRole.SOLVER, UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN]
    )).all()
    target_val = service_enum.value if hasattr(service_enum, 'value') else str(service_enum)
    target_name = service_enum.name if hasattr(service_enum, 'name') else str(service_enum)
    emails = []
    for u in staff:
        if not u.email:
            continue
        allowed = u.get_allowed_services()
        if target_val in allowed or target_name in allowed or 'ADMIN' in str(u.role.value).upper():
            emails.append(u.email)
    return emails


def create_ticket_for_target(row, target, excel_id):
    uid_suffix = target.uid_suffix or target.target_service.value
    uid = f"EXT{excel_id}-{uid_suffix}"
    existing = Ticket.query.filter_by(uid_public=uid).first()
    if existing:
        return existing, False

    type_demande = row.get('Type de demande') or '-'
    author = find_author(row.get('Adresse de messagerie'))

    ticket = Ticket(
        uid_public=uid,
        title=f"[DRH] {type_demande}",
        description=build_description(row),
        author_id=author.id if author else None,
        target_service=target.target_service,
        status=TicketStatus.PENDING,
        category_ticket=type_demande,
        service_demandeur=author.service if (author and hasattr(author, 'service')) else row.get('Nom'),
        tel_demandeur=row.get('Téléphone de contact') or None,
        created_at=excel_serial_to_datetime(row.get('Heure de fin')),
    )
    db.session.add(ticket)
    db.session.flush()
    return ticket, True


def main():
    app = create_app('production')
    with app.app_context():
        token = get_graph_token()
        headers = {"Authorization": f"Bearer {token}"}

        owner_upn = os.environ['SHAREPOINT_DRH_OWNER_UPN']
        filename = os.environ['SHAREPOINT_DRH_EXCEL_FILENAME']

        item_id = find_excel_item_id(headers, owner_upn, filename)
        rows = get_excel_rows(headers, owner_upn, item_id)

        if not rows:
            print("Aucune réponse dans le classeur.")
            return

        dispatch_targets = get_drh_dispatch_targets()

        created_count = 0
        for row in rows:
            excel_id = row.get('Id')
            if excel_id is None:
                continue
            type_demande = row.get('Type de demande')
            targets = targets_for_type_demande(dispatch_targets, type_demande)
            if not targets:
                continue

            attachment_url = row.get("Capture d'écran / Photo")
            tickets = [create_ticket_for_target(row, target, excel_id) for target in targets]

            # Pièce jointe téléchargée au plus une fois par réponse, et
            # seulement si un ticket en a besoin (nouveau, ou existant sans
            # fichier — rattrape un ticket créé alors que le téléchargement
            # avait échoué). Sans ce filtre, chaque passage du cron
            # retéléchargerait toutes les pièces jointes de l'historique.
            needs_attachment = [t for t, _ in tickets if not t.daf_files_json]
            attachment_name = attachment_content = None
            if attachment_url and needs_attachment:
                attachment_name, attachment_content = download_attachment(
                    headers, owner_upn, attachment_url
                )
            if attachment_content:
                for ticket in needs_attachment:
                    attach_file_to_ticket(ticket, attachment_name, attachment_content)
                    print(f"Pièce jointe rattachée à {ticket.uid_public}.")

            for ticket, is_new in tickets:
                if not is_new:
                    continue
                created_count += 1
                print(f"Ticket créé : {ticket.uid_public} (service {ticket.target_service.value}, type demande {type_demande!r}).")
                try:
                    recipients = get_service_emails(ticket.target_service)
                    if recipients and ticket.author:
                        send_service_alert(ticket, recipients)
                    notify_solvers_new_ticket(ticket)
                except Exception as e:
                    print(f"  Attention : notification échouée pour {ticket.uid_public} : {e}")

        db.session.commit()
        print(f"Terminé : {created_count} nouveau(x) ticket(s) créé(s) sur {len(rows)} réponse(s) au total.")


if __name__ == '__main__':
    main()
