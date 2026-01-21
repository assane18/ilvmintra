from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from app import mail

def send_async_email(app, msg):
    """
    Fonction exécutée en arrière-plan (Thread) pour envoyer l'email
    sans bloquer l'application principale.
    """
    with app.app_context():
        try:
            mail.send(msg)
            app.logger.info(f"Email envoyé avec succès : {msg.subject}")
        except Exception as e:
            app.logger.error(f"ERREUR CRITIQUE envoi email async : {e}")

def send_email(subject, sender, recipients, text_body, html_body, attachments=None, cc=None):
    """
    Prépare l'email et lance le thread d'envoi.
    Retourne immédiatement pour ne pas faire attendre l'utilisateur.
    """
    msg = Message(subject, sender=sender, recipients=recipients, cc=cc)
    msg.body = text_body
    msg.html = html_body

    # Gestion des pièces jointes si nécessaire
    if attachments:
        for attachment in attachments:
            try:
                # On suppose que attachment est un tuple (filename, content_type, data)
                # ou un objet avec ces propriétés. Adaptation selon ton code existant.
                msg.attach(*attachment)
            except Exception as e:
                current_app.logger.error(f"Erreur attachement fichier email: {e}")

    # On récupère l'instance réelle de l'app pour la passer au thread
    # C'est CRUCIAL car 'current_app' est un proxy lié au contexte de la requête
    app = current_app._get_current_object()
    
    # Lancement du processus en arrière-plan
    Thread(target=send_async_email, args=(app, msg)).start()


# --- Fonctions Métiers Spécifiques ---

def send_ticket_notification(ticket):
    """Notification de création de ticket"""
    send_email(
        subject=f"[Intranet] Nouveau Ticket #{ticket.uid_public}",
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=[ticket.author.email],  # Ou admin
        text_body=f"Le ticket {ticket.title} a été créé.",
        html_body=render_template('emails/new_ticket.html', ticket=ticket)
    )

def send_fcpi_notification(fcpi):
    """
    Notification spécifique FCPI.
    C'est souvent ici que ça plantait si le SMTP était lent.
    """
    subject = f"[FCPI] Nouvelle demande #{fcpi.uid_public} - {fcpi.site}"
    
    # Détermination des destinataires (ex: Admin FCPI + Auteur)
    recipients = [fcpi.author.email]
    if current_app.config.get('FCPI_ADMIN_EMAIL'):
        recipients.append(current_app.config['FCPI_ADMIN_EMAIL'])
    
    # Création du corps du mail (simple string si pas de template)
    html_content = f"""
    <h3>Nouvelle FCPI Créée</h3>
    <p><strong>Auteur:</strong> {fcpi.author.username}</p>
    <p><strong>Site:</strong> {fcpi.site}</p>
    <p><strong>Description:</strong> {fcpi.description}</p>
    <p><a href="{current_app.config.get('BASE_URL', '')}/fcpi/{fcpi.id}">Voir la fiche complète</a></p>
    """

    send_email(
        subject=subject,
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=recipients,
        text_body="Nouvelle FCPI créée.",
        html_body=html_content
    )
