from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from . import mail

def send_async_email(app, msg):
    """Envoie le mail en arrière-plan"""
    with app.app_context():
        try:
            mail.send(msg)
            print(f"EMAIL SENT: {msg.subject} to {msg.recipients}")
        except Exception as e:
            print(f"EMAIL ERROR: {e}")

def send_email(to, subject, template, **kwargs):
    """
    Prépare et lance l'envoi du mail.
    :param to: Email du destinataire (string) ou liste
    :param subject: Sujet du mail
    :param template: Nom du fichier HTML (sans extension, ex: 'new_ticket')
    :param kwargs: Variables à passer au template (user, ticket, etc.)
    """
    app = current_app._get_current_object()
    
    # On s'assure que 'to' est une liste
    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = to

    msg = Message(
        subject=f"[INTRANET ILVM] {subject}",
        recipients=recipients,
        sender=app.config['MAIL_DEFAULT_SENDER']
    )
    
    # On peut créer un corps texte et HTML
    # msg.body = render_template(f'emails/{template}.txt', **kwargs)
    msg.html = render_template(f'emails/{template}.html', **kwargs)
    
    # Lancement dans un thread séparé
    thr = Thread(target=send_async_email, args=(app, msg))
    thr.start()
    return thr
