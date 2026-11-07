#!/usr/bin/env python3
"""Robot de publication Instagram d'Elite Recovery.

Toutes les 30 minutes, GitHub lance ce script. Il regarde dans calendrier.json s'il y a un post
prévu aujourd'hui dont l'heure est passée, et le publie sur @eliterecovery.ch avec l'API officielle
d'Instagram (images du dossier images/ de ce dépôt public, légende + hashtags).
Chaque post publié est noté dans publies.json : il n'est jamais publié deux fois, et l'app le coche toute seule.

Secrets GitHub (Settings › Secrets and variables › Actions) :
  IG_TOKEN    jeton d'accès Instagram (API Instagram avec connexion Instagram)
Variables facultatives :
  IG_PAUSE    « oui » pour mettre le robot en pause sans rien supprimer
"""
import json, os, sys, time, datetime, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ICI = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Zurich")
API = "https://graph.instagram.com/v25.0"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "eliterecovery/instagram")
IMAGES = f"https://raw.githubusercontent.com/{DEPOT}/main/images/"
TOKEN = os.environ.get("IG_TOKEN", "").strip()
ESSAI = "--essai" in sys.argv or not TOKEN


def appel(methode, chemin, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{chemin}"
    data = None
    if methode == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Instagram a refusé ({e.code}) : {e.read().decode()[:500]}")


def attendre(conteneur):
    for _ in range(40):
        s = appel("GET", conteneur, fields="status_code").get("status_code")
        if s == "FINISHED":
            return
        if s in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Image refusée par Instagram (statut {s})")
        time.sleep(5)
    raise RuntimeError("Instagram n'a pas fini de préparer le post à temps")


def deja_en_ligne(post):
    """Évite le doublon si le post a déjà été publié à la main depuis l'app."""
    debut = post["l"].strip()[:60]
    try:
        r = appel("GET", "me/media", fields="caption,timestamp", limit=12)
    except Exception:
        return None
    for m in r.get("data", []):
        if (m.get("caption") or "").strip().startswith(debut):
            return m.get("id")
    return None


def publier(post):
    legende = (post["l"].strip() + "\n\n" + post["g"].strip()).strip()
    noms = post["i"]
    if len(noms) == 1:
        c = appel("POST", "me/media", image_url=IMAGES + urllib.parse.quote(noms[0]), caption=legende)["id"]
        attendre(c)
    else:
        enfants = []
        for n in noms[:10]:
            e = appel("POST", "me/media", image_url=IMAGES + urllib.parse.quote(n), is_carousel_item="true")["id"]
            attendre(e)
            enfants.append(e)
        c = appel("POST", "me/media", media_type="CAROUSEL", children=",".join(enfants), caption=legende)["id"]
        attendre(c)
    return appel("POST", "me/media_publish", creation_id=c)["id"]


def main():
    if os.environ.get("IG_PAUSE", "").lower() in ("oui", "yes", "1"):
        print("Robot en pause (variable IG_PAUSE).")
        return
    cal = json.load(open(os.path.join(ICI, "calendrier.json"), encoding="utf-8"))
    chemin_pub = os.path.join(ICI, "publies.json")
    pub = json.load(open(chemin_pub, encoding="utf-8")) if os.path.exists(chemin_pub) else {}
    maintenant = datetime.datetime.now(TZ)
    auj = maintenant.date().isoformat()
    a_faire = [p for p in cal if p.get("d") == auj and p["d"] not in pub and p.get("auto")
               and maintenant.strftime("%H:%M") >= p["auto"]]
    prochain = next((p for p in cal if p.get("d") and p.get("auto") and (p["d"], p["auto"]) > (auj, maintenant.strftime("%H:%M")) and p["d"] not in pub), None)
    if not a_faire:
        print("Rien à publier maintenant." + (f" Prochain : {prochain['d']} à {prochain['auto']} · {prochain['t']}" if prochain else ""))
        return
    for p in a_faire:
        if ESSAI:
            print(f"[ESSAI, sans jeton] Je publierais : {p['d']} {p['auto']} · {p['t']} · {len(p['i'])} image(s)")
            continue
        existant = deja_en_ligne(p)
        if existant:
            print(f"Déjà sur Instagram (publié à la main) : {p['t']}")
            pub[p["d"]] = {"t": p["t"], "id": existant, "le": maintenant.isoformat(), "par": "main"}
        else:
            ident = publier(p)
            print(f"Publié : {p['d']} · {p['t']} (id {ident})")
            pub[p["d"]] = {"t": p["t"], "id": ident, "le": maintenant.isoformat(), "par": "robot"}
        json.dump(pub, open(chemin_pub, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rafraichir():
    """Prolonge le jeton de 60 jours (lancé chaque lundi)."""
    if not TOKEN:
        print("Pas de jeton : rien à prolonger.")
        return
    r = urllib.request.urlopen(f"https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={TOKEN}", timeout=60)
    j = json.loads(r.read().decode())
    jours = int(j.get("expires_in", 0)) // 86400
    print(f"Jeton prolongé : valable encore {jours} jours.")
    nouveau = j.get("access_token", "")
    if nouveau and nouveau != TOKEN:
        open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a").write("nouveau=oui\n")
        open("/tmp/nouveau_jeton", "w").write(nouveau)


if __name__ == "__main__":
    if "--rafraichir" in sys.argv:
        rafraichir()
    else:
        main()
