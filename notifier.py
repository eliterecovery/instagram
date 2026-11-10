#!/usr/bin/env python3
"""Notification sur l'iPhone de Quentin (app Elite Recovery) dès qu'un post vient d'être publié.

Passe par le service de notifications d'Apple (APNs), avec la clé créée sur developer.apple.com.
Secrets GitHub (Settings › Secrets and variables › Actions) :
  APNS_KEY_P8   le texte du fichier AuthKey_XXXXXXXXXX.p8 (lignes BEGIN et END comprises)
  APNS_KEY_ID   le Key ID (10 caractères)
  APNS_IPHONE   le code de l'iPhone (app › Studio › Notifications › Copier) ; plusieurs : séparés par des virgules
Sans ces secrets, rien n'est envoyé et la publication continue normalement.
"""
import base64, json, os, subprocess, sys, time

TEAM = os.environ.get("APNS_TEAM_ID", "").strip() or "6L9PARYX7B"
SUJET = "ch.eliterecovery.app"
SERVEUR = os.environ.get("APNS_SERVEUR", "https://api.push.apple.com")   # TestFlight et App Store : production


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jeton(cle_p8, key_id):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    texte = cle_p8.replace("\r", "").strip()
    if "BEGIN PRIVATE KEY" not in texte:
        raise ValueError("APNS_KEY_P8 doit contenir le texte du fichier .p8, lignes BEGIN et END comprises")
    cle = serialization.load_pem_private_key(texte.encode(), password=None)
    tete = _b64(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")).encode())
    corps = _b64(json.dumps({"iss": TEAM, "iat": int(time.time())}, separators=(",", ":")).encode())
    der = cle.sign(f"{tete}.{corps}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{tete}.{corps}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def envoyer(titre, texte, extra=None):
    """Envoie la notification ; ne lève jamais d'erreur (la publication ne doit pas en dépendre)."""
    cle, kid = os.environ.get("APNS_KEY_P8", ""), os.environ.get("APNS_KEY_ID", "").strip()
    iphones = [x.strip().replace(" ", "").replace("<", "").replace(">", "") for x in os.environ.get("APNS_IPHONE", "").split(",") if x.strip()]
    if not cle or not kid:
        print("Notification iPhone : secrets APNS_KEY_P8 et APNS_KEY_ID absents, rien envoyé.")
        return False
    if not iphones:
        print("Notification iPhone : secret APNS_IPHONE absent (code de l'iPhone, app › Studio › Notifications), rien envoyé.")
        return False
    try:
        jeton = _jeton(cle, kid)
    except Exception as e:
        print(f"Notification iPhone : clé illisible ({e}).")
        return False
    charge = {"aps": {"alert": {"title": titre, "body": texte}, "sound": "default", "content-available": 1}}
    charge.update(extra or {})
    ok = False
    for tel in iphones:
        try:
            r = subprocess.run(["curl", "-sS", "--http2", "-o", "/tmp/apns.txt", "-w", "%{http_code}",
                                "-H", f"authorization: bearer {jeton}", "-H", f"apns-topic: {SUJET}",
                                "-H", "apns-push-type: alert", "-H", "apns-priority: 10",
                                "--data-binary", json.dumps(charge, ensure_ascii=False),
                                f"{SERVEUR}/3/device/{tel}"], capture_output=True, text=True, timeout=30)
            code = r.stdout.strip()
            detail = open("/tmp/apns.txt").read().strip() if os.path.exists("/tmp/apns.txt") else r.stderr.strip()
            if code == "200":
                print(f"Notification iPhone envoyée (…{tel[-6:]}).")
                ok = True
            else:
                print(f"Notification iPhone refusée par Apple ({code}) : {detail}")
        except Exception as e:
            print(f"Notification iPhone impossible : {e}")
    return ok


if __name__ == "__main__":
    # Essai : python3 notifier.py  (bouton Run workflow, mode « notifier »)
    envoyer("Notifications du robot : OK", "C’est ainsi que tu seras prévenu à chaque post publié sur Instagram.",
            {"lien": "eliterecovery://onglet/social"})
