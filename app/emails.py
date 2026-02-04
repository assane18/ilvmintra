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

def send_email(subject, recipients, text_body, html_body):
    if not recipients:
        return
    
    msg = Message(subject, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    msg.sender = current_app.config['MAIL_DEFAULT_SENDER']

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
    send_email(f"[Message] {ticket.title}", [recipient.email], message_content, full_html)

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
    
    <p>Merci de votre confiance.</p>
    """
    
    full_html = get_outlook_friendly_html("Ticket Résolu", html_content, link, "Voir l'historique")
    send_email(f"[Résolu] {ticket.title}", [ticket.author.email], "Ticket terminé.", full_html)
