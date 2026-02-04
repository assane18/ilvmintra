import smtplib
import socket
from email.mime.text import MIMEText
from datetime import datetime

# --- TA CONFIGURATION INTERNE ---
EXCHANGE_SERVER = "ILVMExchangeSrv.Ilvm.lan"
EXCHANGE_PORT = 25  # Port standard interne (pas de chiffrement SSL/TLS requis)

# MODIFIE L'ADRESSE DU DESTINATAIRE POUR TESTER
SENDER_EMAIL = "no-reply-intranet@ilvm.lan"
TARGET_EMAIL = "astraore@ilvm.lan" # Mets ton email pro ici

def test_local_exchange():
    print(f"--- TEST VERS {EXCHANGE_SERVER} ---")
    
    msg = MIMEText(f"Test envoyé depuis la Debian le {datetime.now()}")
    msg['Subject'] = "[TEST] Connexion Exchange Interne OK"
    msg['From'] = SENDER_EMAIL
    msg['To'] = TARGET_EMAIL

    try:
        # 1. Test DNS
        print(f"[1/4] Résolution DNS de {EXCHANGE_SERVER}...")
        ip = socket.gethostbyname(EXCHANGE_SERVER)
        print(f"      -> OK : {ip}")

        # 2. Connexion
        print(f"[2/4] Connexion au port {EXCHANGE_PORT}...")
        server = smtplib.SMTP(EXCHANGE_SERVER, EXCHANGE_PORT, timeout=10)
        server.set_debuglevel(1) # Affiche les échanges techniques
        print("      -> Connecté.")

        # Pas de starttls() ni de login() sur le port 25 interne en général
        
        # 3. Envoi
        print(f"[3/4] Envoi du mail de {SENDER_EMAIL} vers {TARGET_EMAIL}...")
        server.sendmail(SENDER_EMAIL, [TARGET_EMAIL], msg.as_string())
        
        print("✅ SUCCÈS ! Le serveur Exchange a accepté le mail.")
        server.quit()

    except socket.gaierror:
        print("❌ ERREUR DNS : La Debian ne trouve pas 'ILVMExchangeSrv.Ilvm.lan'.")
        print("   Solution : Ajoute l'IP du serveur dans /etc/hosts si le DNS interne n'est pas configuré.")
    except ConnectionRefusedError:
        print("❌ ERREUR PORT : Le port 25 est fermé ou bloqué.")
    except smtplib.SMTPRecipientsRefused:
        print("❌ ERREUR RELAIS : Le serveur refuse d'envoyer à ce destinataire (Relais interdit).")
        print("   Solution : Demande à l'admin Exchange d'ajouter l'IP de la Debian dans le 'Receive Connector'.")
    except Exception as e:
        print(f"❌ ERREUR : {e}")

if __name__ == "__main__":
    test_local_exchange()
