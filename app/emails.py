from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from . import mail

def send_async_email(app, msg):
    """Envoie le mail dans un thread séparé"""
    with app.app_context():
        try:
            mail.send(msg)
            print(f"EMAIL SENT: {msg.subject} to {msg.recipients}")
        except Exception as e:
            print(f"EMAIL ERROR: {e}")

def send_email(to, subject, template, **kwargs):
    """
    Prépare et envoie un email.
    :param to: Email destinataire
    :param subject: Sujet
    :param template: Nom du template HTML (sans extension) dans templates/emails/
    :param kwargs: Variables passées au template (user, ticket, etc.)
    """
    app = current_app._get_current_object()
    
    msg = Message(
        subject=f"[INTRANET] {subject}",
        recipients=[to],
        sender=app.config['MAIL_DEFAULT_SENDER']
    )
    
    # On charge le corps du mail depuis un template HTML
    msg.html = render_template(f'emails/{template}.html', **kwargs)
    
    thr = Thread(target=send_async_email, args=(app, msg))
    thr.start()
    return thr
