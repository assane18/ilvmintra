from threading import Thread
from flask import current_app
from flask_mail import Message
from app import mail
import os

# --- COULEURS ---
STYLE_COLOR = "#2563eb"  # Bleu ILVM
BG_COLOR = "#edf2f7"     # Gris fond

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            print(f"✅ EMAIL ENVOYÉ : {msg.subject}")
        except Exception as e:
            print(f"❌ ERREUR EMAIL : {e}")

def get_outlook_friendly_html(title, content, link_url=None, link_text="Voir le ticket"):
    """ 
    Génère un HTML compatible Outlook 2016 (Table-based layout).
    L'image logo est référencée par 'cid:logo'.
    """
    
    # Bouton compatible Outlook (Tableau imbriqué)
    button_html = ""
    if link_url:
        button_html = f"""
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin-top: 20px;">
          <tr>
            <td align="center" bgcolor="{STYLE_COLOR}" style="border-radius: 6px;">
              <a href="{link_url}" target="_blank" style="font-family: Arial, sans-serif; font-size: 16px; color: #ffffff; text-decoration: none; text-decoration: none; border-radius: 6px; padding: 12px 24px; border: 1px solid {STYLE_COLOR}; display: inline-block; font-weight: bold;">
                {link_text}
              </a>
            </td>
          </tr>
        </table>
        """

    return f"""
    <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
    <html xmlns="http://www.w3.org/1999/xhtml">
    <head>
      <meta name="viewport" content="width=device-width" />
      <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
      <title>{title}</title>
      <style type="text/css">
        body {{ margin: 0; padding: 0; background-color: {BG_COLOR}; font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333; }}
        img {{ border: none; -ms-interpolation-mode: bicubic; display: block; }}
        /* Hack pour Outlook qui force parfois Times New Roman */
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; font-family: Arial, sans-serif; }} 
      </style>
    </head>
    <body bgcolor="{BG_COLOR}">
    
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" bgcolor="{BG_COLOR}">
        <tr>
          <td align="center" style="padding: 20px 0;">
            
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600" style="width: 600px;">
              <tr>
                <td align="center" style="padding-bottom: 20px;">
                  <img src="cid:logo" alt="ILVM Intranet" width="150" style="width: 150px; height: auto;">
                </td>
              </tr>
            </table>

            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600" style="width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
              
              <tr>
                <td bgcolor="{STYLE_COLOR}" height="4" style="height: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
              </tr>

              <tr>
                <td style="padding: 30px;">
                  <h2 style="margin: 0 0 15px 0; font-size: 20px; color: #2d3748;">{title}</h2>
                  
                  <div style="font-size: 15px; color: #4a5568;">
                    {content}
                  </div>

                  {button_html}
                  
                  <p style="margin-top: 30px; font-size: 12px; color: #a0aec0; text-align: center;">
                    Ceci est un message automatique de l'Intranet ILVM.<br>
                    Ne répondez pas à cet email.
                  </p>
                </td>
              </tr>
            </table>
            
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600">
                <tr><td height="40">&nbsp;</td></tr>
            </table>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """

# Types d'e-mail, pour la préférence User.email_mode :
#   'message'   -> retenu pour les utilisateurs en mode "important" et "daily"
#   'important' -> retenu seulement pour les utilisateurs en mode "daily"
#   'digest'    -> toujours envoyé (résumés, relances, récaps : c'est LE canal des modes réduits)
def filter_recipients_by_preference(recipients, kind):
    if kind == 'digest' or not recipients:
        return list(recipients or [])
    from app.models import User
    from sqlalchemy import func
    lowered = [r.lower() for r in recipients if r]
    modes = {u.email.lower(): (u.email_mode or 'all')
             for u in User.query.filter(func.lower(User.email).in_(lowered)).all() if u.email}
    kept = []
    for r in recipients:
        mode = modes.get((r or '').lower(), 'all')
        if mode == 'daily':
            continue
        if mode == 'important' and kind == 'message':
            continue
        kept.append(r)
    return kept

def send_email(subject, recipients, text_body, html_body, kind='important'):
    recipients = filter_recipients_by_preference(recipients, kind)
    if not recipients:
        return

    sender = current_app.config['MAIL_DEFAULT_SENDER']
    # Destinataires en CCI : évite que chaque destinataire voie la liste des autres
    # (ex. alerte à tout un service, formulaire à plusieurs validateurs).
    msg = Message(subject, recipients=[sender], bcc=recipients)
    msg.body = text_body
    msg.html = html_body
    msg.sender = sender

    # --- CORRECTION ICI : Headers doit être un dictionnaire {} ---
    try:
        with current_app.open_resource("static/img/logo.png") as fp:
            msg.attach(
                "logo.png", 
                "image/png", 
                fp.read(), 
                'inline', 
                headers={'Content-ID': '<logo>'} # <--- C'est ici que j'ai corrigé [] par {}
            )
    except Exception as e:
        print(f"⚠️ Attention : Impossible d'attacher le logo (Fichier manquant ?). Erreur : {e}")
    # -------------------------------------------------------------

    app = current_app._get_current_object()
    Thread(target=send_async_email, args=(app, msg)).start()

# --- 1. ALERTE CRÉATION ---
def send_service_alert(ticket, recipients_emails):
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/tickets/view/{ticket.uid_public}"
    
    html_content = f"""
    <p>Bonjour,</p>
    <p>Une nouvelle demande a été créée pour votre service.</p>
    
    <table border="0" cellpadding="8" cellspacing="0" width="100%" style="background-color: #f7fafc; border-left: 4px solid {STYLE_COLOR}; margin: 15px 0;">
        <tr>
            <td width="30%" style="font-weight: bold; color: #718096;">Demandeur :</td>
            <td>{ticket.author.fullname}</td>
        </tr>
        <tr>
            <td style="font-weight: bold; color: #718096;">Sujet :</td>
            <td>{ticket.title}</td>
        </tr>
    </table>
    
    <p style="margin-top: 15px;"><strong>Description :</strong></p>
    <p style="background-color: #fff; border: 1px solid #e2e8f0; padding: 10px; border-radius: 4px;">{ticket.description}</p>
    """
    
    full_html = get_outlook_friendly_html("Nouveau Ticket", html_content, link, "Accéder au Ticket")
    send_email(f"[Nouveau] {ticket.title}", recipients_emails, ticket.description, full_html)

# --- 2. NOTIFICATION ASSIGNATION ---
def send_assignment_notification(ticket, solver):
    if not solver.email: return
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/tickets/view/{ticket.uid_public}"

    html_content = f"""
    <p>Bonjour {solver.fullname},</p>
    <p>Le ticket <strong>#{ticket.uid_public}</strong> vous a été attribué.</p>
    <br>
    <table border="0" cellpadding="0" cellspacing="0" width="100%">
        <tr>
            <td align="center" style="font-size: 16px; font-weight: bold; color: #2d3748;">
                {ticket.title}
            </td>
        </tr>
    </table>
    """
    
    full_html = get_outlook_friendly_html("Ticket Assigné", html_content, link, "Traiter la demande")
    send_email(f"[Assignation] {ticket.uid_public}", [solver.email], f"Ticket {ticket.uid_public} assigné.", full_html)

# --- 3. NOTIFICATION MESSAGE ---
def send_message_notification(ticket, message_content, recipient):
    if not recipient.email: return
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/tickets/view/{ticket.uid_public}"

    html_content = f"""
    <p>Bonjour,</p>
    <p>Nouveau message sur le ticket <strong>#{ticket.uid_public}</strong> :</p>
    
    <table border="0" cellpadding="15" cellspacing="0" width="100%" style="margin-top: 10px; border: 1px solid #e2e8f0; background-color: #ebf8ff; border-radius: 5px;">
        <tr>
            <td style="font-style: italic; color: #2c5282;">
                "{message_content}"
            </td>
        </tr>
    </table>
    """
    
    full_html = get_outlook_friendly_html(f"Message sur {ticket.uid_public}", html_content, link, "Répondre")
    send_email(f"[Message] {ticket.title}", [recipient.email], message_content, full_html, kind='message')

# --- 4. NOTIFICATION CLÔTURE ---
def send_closure_notification(ticket):
    if not ticket.author.email: return
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/tickets/view/{ticket.uid_public}"

    html_content = f"""
    <p>Bonjour {ticket.author.fullname},</p>
    <p>Bonne nouvelle ! Votre ticket <strong>#{ticket.uid_public}</strong> a été résolu et clôturé.</p>
    
    <table border="0" cellpadding="10" cellspacing="0" width="100%" style="margin: 15px 0;">
        <tr>
            <td align="center" bgcolor="#c6f6d5" style="color: #22543d; font-weight: bold; border-radius: 4px;">
                ✅ STATUT : TERMINÉ
            </td>
        </tr>
    </table>
    
    <p style="margin-top:18px;"><strong>Votre avis compte</strong> — un clic suffit :</p>
    <table border="0" cellpadding="0" cellspacing="0" style="margin: 8px 0 18px;">
        <tr>
            <td style="padding-right:8px;"><a href="{base_url}tickets/rate/{ticket.uid_public}/3" style="display:inline-block;padding:10px 16px;background:#059669;color:#fff;text-decoration:none;font-weight:bold;border-radius:4px;">&#128522; Satisfait</a></td>
            <td style="padding-right:8px;"><a href="{base_url}tickets/rate/{ticket.uid_public}/2" style="display:inline-block;padding:10px 16px;background:#d97706;color:#fff;text-decoration:none;font-weight:bold;border-radius:4px;">&#128528; Moyen</a></td>
            <td><a href="{base_url}tickets/rate/{ticket.uid_public}/1" style="display:inline-block;padding:10px 16px;background:#dc2626;color:#fff;text-decoration:none;font-weight:bold;border-radius:4px;">&#128577; Insatisfait</a></td>
        </tr>
    </table>
    <p style="font-size:12px;color:#718096;">Ce n'est pas résolu ? Vous pouvez rouvrir la demande depuis le ticket pendant 7 jours.</p>
    <p>Merci de votre confiance.</p>
    """
    
    full_html = get_outlook_friendly_html("Ticket Résolu", html_content, link, "Voir le ticket")
    send_email(f"[Résolu] {ticket.title}", [ticket.author.email], "Ticket terminé.", full_html)

# --- RELANCE QUOTIDIENNE TICKETS EN RETARD (ajouté 2026-09-17) ---
def send_stale_tickets_reminder(recipient_email, tickets, assigned_to_me):
    """Un seul email groupé par destinataire (pas un par ticket) listant les
    tickets PENDING/IN_PROGRESS créés il y a plus de 24h. `assigned_to_me`
    distingue le message ("tes tickets" vs "tickets non pris en charge de ton
    service") — voir scripts/relance_tickets.py, lancé une fois par jour."""
    base_url = current_app.config.get('BASE_URL', '')

    rows = ""
    for t in tickets:
        link = f"{base_url}/tickets/view/{t.uid_public}"
        age_j = int(t.age_hours // 24)
        rows += f"""
        <tr>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;"><a href="{link}">#{t.uid_public}</a></td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{t.title}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0; text-align:center;">{age_j} j</td><td style="padding:6px; border-bottom:1px solid #e2e8f0; text-align:center; color:#b91c1c;">{t.sla_label}</td>
        </tr>"""

    intro = (
        "Les tickets suivants te sont assignés et ont dépassé leur délai cible :"
        if assigned_to_me else
        "Les tickets suivants attendent d'être pris en charge dans votre service et ont dépassé leur délai cible :"
    )

    html_content = f"""
    <p>Bonjour,</p>
    <p>{intro}</p>
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse; margin: 15px 0;">
        <tr style="background-color:#f7fafc;">
            <th style="padding:6px; text-align:left;">Ticket</th>
            <th style="padding:6px; text-align:left;">Titre</th>
            <th style="padding:6px; text-align:center;">Âge</th><th style="padding:6px; text-align:center;">Délai cible</th>
        </tr>
        {rows}
    </table>
    <p style="font-size:12px; color:#718096;">Ce rappel se répète chaque jour tant que le ticket reste ouvert.</p>
    """

    full_html = get_outlook_friendly_html("Tickets en retard", html_content)
    send_email(
        f"🔔 Rappel : {len(tickets)} ticket(s) hors délai",
        [recipient_email],
        f"{len(tickets)} ticket(s) en retard.",
        full_html,
        kind='digest',
    )

# --- 5. ALERTE ÉTAPE FORMULAIRE À VALIDER ---
def send_form_step_alert(submission, step, recipients_emails):
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/forms/submission/{submission.id}"

    html_content = f"""
    <p>Bonjour,</p>
    <p>Un formulaire est en attente de votre validation.</p>

    <table border="0" cellpadding="8" cellspacing="0" width="100%" style="background-color: #f7fafc; border-left: 4px solid {STYLE_COLOR}; margin: 15px 0;">
        <tr>
            <td width="30%" style="font-weight: bold; color: #718096;">Formulaire :</td>
            <td>{submission.form.name}</td>
        </tr>
        <tr>
            <td style="font-weight: bold; color: #718096;">Demandeur :</td>
            <td>{submission.author_name}</td>
        </tr>
        <tr>
            <td style="font-weight: bold; color: #718096;">Étape :</td>
            <td>{step.label}</td>
        </tr>
    </table>
    """

    full_html = get_outlook_friendly_html("Formulaire à valider", html_content, link, "Voir et valider")
    send_email(f"[À valider] {submission.form.name} — {submission.uid_public}", recipients_emails,
               f"Formulaire {submission.uid_public} en attente de validation ({step.label}).", full_html)

# --- 6. NOTIFICATION REFUS FORMULAIRE ---
def send_form_refused_notification(submission, recipient_email):
    if not recipient_email:
        return
    base_url = current_app.config.get('BASE_URL', '')
    link = f"{base_url}/forms/submission/{submission.id}"

    html_content = f"""
    <p>Bonjour {submission.author_name},</p>
    <p>Votre formulaire <strong>{submission.form.name}</strong> (#{submission.uid_public}) a été refusé.</p>

    <table border="0" cellpadding="15" cellspacing="0" width="100%" style="margin-top: 10px; border: 1px solid #fed7d7; background-color: #fff5f5; border-radius: 5px;">
        <tr>
            <td style="color: #c53030;">
                {submission.refusal_reason or 'Aucun motif renseigné.'}
            </td>
        </tr>
    </table>
    """

    full_html = get_outlook_friendly_html("Formulaire refusé", html_content, link, "Voir le formulaire")
    send_email(f"[Refusé] {submission.form.name} — {submission.uid_public}", [recipient_email],
               submission.refusal_reason or "Formulaire refusé.", full_html)


# --- RÉSUMÉ QUOTIDIEN (utilisateurs en mode e-mail "daily") ---
def send_daily_digest(user, notifications):
    base_url = current_app.config.get('BASE_URL', '').rstrip('/')
    rows = ""
    for n in notifications:
        link = f"{base_url}{n.link}" if n.link else base_url
        when = n.timestamp.strftime('%d/%m %H:%M') if n.timestamp else ''
        rows += f"""
        <tr>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0; white-space:nowrap; color:#718096;">{when}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;"><a href="{link}">{n.message}</a></td>
        </tr>"""
    html_content = f"""
    <p>Bonjour {user.fullname or user.username},</p>
    <p>Voici ce qui s'est passé sur vos demandes ces dernières 24 heures ({len(notifications)} événement(s)) :</p>
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse; margin: 15px 0;">{rows}</table>
    <p style="font-size:12px; color:#718096;">Vous recevez ce résumé parce que vous avez choisi « un résumé par jour » dans votre profil. Modifiable à tout moment dans Mon profil &gt; Mon compte.</p>
    """
    full_html = get_outlook_friendly_html("Résumé quotidien", html_content, f"{base_url}/my_history", "Voir mes demandes")
    send_email("[Intranet] Résumé quotidien de vos demandes", [user.email], f"{len(notifications)} événement(s)", full_html, kind='digest')


# --- RÉCAP HEBDOMADAIRE MANAGERS / DIRECTEURS (lundi 8h, scripts/recap_hebdo_managers.py) ---
def send_weekly_manager_digest(user, data):
    base_url = current_app.config.get('BASE_URL', '').rstrip('/')
    now = data['now']

    def age(dt):
        d = (now - dt).days
        return f"{d} j" if d else "aujourd'hui"

    def ticket_rows(tickets):
        return "".join(f"""
        <tr>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;"><a href="{base_url}/tickets/view/{t.uid_public}">#{t.uid_public}</a></td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{t.title}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{t.author.fullname if t.author else ''}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0; text-align:center; white-space:nowrap;">{age(t.created_at)}</td>
        </tr>""" for t in tickets)

    def sub_rows(subs):
        return "".join(f"""
        <tr>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;"><a href="{base_url}/forms/submission/{s.id}">{s.uid_public}</a></td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{s.form.name if s.form else 'Formulaire'}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{s.author.fullname if s.author else ''}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0; text-align:center; white-space:nowrap;">{age(s.created_at)}</td>
        </tr>""" for s in subs)

    head = """<tr style="background-color:#f7fafc;"><th style="padding:6px; text-align:left;">Réf.</th><th style="padding:6px; text-align:left;">Objet</th><th style="padding:6px; text-align:left;">Demandeur</th><th style="padding:6px; text-align:center;">Ancienneté</th></tr>"""
    sections = ""
    pending = data['pending_tickets']; subs = data['pending_submissions']
    if pending or subs:
        sections += f"""
        <h3 style="margin:18px 0 6px; color:#b45309;">⏳ En attente de votre validation ({len(pending) + len(subs)})</h3>
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">{head}{ticket_rows(pending)}{sub_rows(subs)}</table>"""
    if data['stale']:
        sections += f"""
        <h3 style="margin:18px 0 6px; color:#b91c1c;">🔴 Tickets en retard sur vos services ({len(data['stale'])})</h3>
        <p style="font-size:12px; color:#718096; margin:0 0 6px;">Non pris en charge ou en cours au-delà de leur délai cible (SLA).</p>
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">{head}{ticket_rows(data['stale'])}</table>"""
    sections += f"""
        <h3 style="margin:18px 0 6px; color:#1e40af;">📥 Reçu cette semaine sur vos services ({len(data['received_week'])})</h3>
        <p style="font-size:12px; color:#718096; margin:0;">{', '.join(data['services']) or 'aucun service géré'}</p>"""

    html_content = f"""
    <p>Bonjour {user.fullname or user.username},</p>
    <p>Votre point hebdomadaire sur les demandes qui vous concernent :</p>
    {sections}
    <p style="font-size:12px; color:#718096; margin-top:18px;">Envoyé chaque lundi matin uniquement s'il y a quelque chose à traiter.</p>
    """
    full_html = get_outlook_friendly_html("Récap hebdomadaire", html_content, f"{base_url}/tickets/manager", "Ouvrir mes validations")
    n = len(pending) + len(subs)
    subject = f"[Intranet] {n} demande(s) attendent votre validation" if n else f"[Intranet] Récap hebdomadaire — {len(data['stale'])} ticket(s) en retard"
    send_email(subject, [user.email], "Récap hebdomadaire", full_html, kind='digest')
