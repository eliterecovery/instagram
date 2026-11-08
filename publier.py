#!/usr/bin/env python3
"""Robot de publication Instagram d'Elite Recovery.

Toutes les 30 minutes, GitHub lance ce script. Il regarde dans calendrier.json s'il y a un post
prévu aujourd'hui dont l'heure est passée, et le publie sur @eliterecovery.ch avec l'API officielle
d'Instagram (images du dossier images/ de ce dépôt public, légende + hashtags).
Chaque post publié est noté dans publies.json : il n'est jamais publié deux fois, et l'app le coche toute seule.

Secrets GitHub (Settings › Secrets and variables › Actions) :
  IG_TOKEN    token d'accès (API Instagram avec connexion unifiée, token système sans expiration)
  IG_USER_ID  identifiant du compte Instagram eliterecovery.ch (affiché à côté du token)
Variables facultatives :
  IG_PAUSE    « oui » pour mettre le robot en pause sans rien supprimer
"""
import json, os, sys, time, datetime, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ICI = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Zurich")
# Connexion unifiée (nouvelles apps Meta) : token système qui n'expire jamais, sur graph.facebook.com
API = os.environ.get("IG_API", "https://graph.facebook.com/v25.0")
IG = os.environ.get("IG_USER_ID", "").strip() or "17841480660654060"  # eliterecovery.ch
DEPOT = os.environ.get("GITHUB_REPOSITORY", "eliterecovery/instagram")
IMAGES = f"https://raw.githubusercontent.com/{DEPOT}/main/images/"
STORIES = f"https://raw.githubusercontent.com/{DEPOT}/main/stories/"
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
        r = appel("GET", f"{IG}/media", fields="caption,timestamp", limit=12)
    except Exception:
        return None
    for m in r.get("data", []):
        if (m.get("caption") or "").strip().startswith(debut):
            return m.get("id")
    return None


LIEU = os.environ.get("IG_LOCATION_ID", "").strip() or "1067322709806644"   # Page Facebook avec adresse (Prilly) : lieu affiché sur le post


def publier(post, lieu=True):
    """Publie le post ; si Instagram refuse le lieu, republie sans lieu."""
    if lieu and LIEU:
        try:
            return _publier(post, LIEU)
        except RuntimeError as e:
            print("Lieu refusé, publication sans lieu :", str(e)[:200])
    return _publier(post, "")


def _publier(post, lieu):
    extra = {"location_id": lieu} if lieu else {}
    legende = (post["l"].strip() + "\n\n" + post["g"].strip()).strip()
    noms = post["i"]
    if len(noms) == 1:
        c = appel("POST", f"{IG}/media", image_url=IMAGES + urllib.parse.quote(noms[0]), caption=legende, **extra)["id"]
        attendre(c)
    else:
        enfants = []
        for n in noms[:10]:
            e = appel("POST", f"{IG}/media", image_url=IMAGES + urllib.parse.quote(n), is_carousel_item="true")["id"]
            attendre(e)
            enfants.append(e)
        c = appel("POST", f"{IG}/media", media_type="CAROUSEL", children=",".join(enfants), caption=legende, **extra)["id"]
        attendre(c)
    return appel("POST", f"{IG}/media_publish", creation_id=c)["id"]


def publier_story(post):
    """Story qui annonce le post (stories/<date>_story.jpg). Un échec ne bloque pas le post."""
    if os.environ.get("IG_STORY", "oui").lower() in ("non", "no", "0"):
        return None
    nom = f"{post['d']}_story.jpg"
    if not os.path.exists(os.path.join(ICI, "stories", nom)):
        return None
    try:
        c = appel("POST", f"{IG}/media", image_url=STORIES + nom, media_type="STORIES")["id"]
        attendre(c)
        return appel("POST", f"{IG}/media_publish", creation_id=c)["id"]
    except Exception as e:
        print("Story non publiée :", e)
        return None


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
            print(f"[ESSAI, sans jeton] Je publierais : {p['d']} {p['auto']} · {p['t']} · {len(p['i'])} image(s) + story")
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
            st = publier_story(p)
            if st:
                print(f"Story publiée (id {st})")
                pub[p["d"]]["story"] = st
        json.dump(pub, open(chemin_pub, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rafraichir():
    """Prolonge le jeton de 60 jours (lancé chaque lundi)."""
    if not TOKEN or "graph.facebook.com" in API:
        print("Token système de la connexion unifiée : il n'expire pas, rien à prolonger.")
        return
    r = urllib.request.urlopen(f"https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={TOKEN}", timeout=60)
    j = json.loads(r.read().decode())
    jours = int(j.get("expires_in", 0)) // 86400
    print(f"Jeton prolongé : valable encore {jours} jours.")
    nouveau = j.get("access_token", "")
    if nouveau and nouveau != TOKEN:
        open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a").write("nouveau=oui\n")
        open("/tmp/nouveau_jeton", "w").write(nouveau)


def verifier():
    """Vérifie le jeton et le compte, sans rien publier."""
    if not TOKEN:
        print("ÉCHEC : le secret IG_TOKEN est vide."); sys.exit(1)
    moi = appel("GET", IG, fields="username,name,media_count")
    print(f"Compte : @{moi.get('username')} · {moi.get('media_count')} publications")
    lim = appel("GET", f"{IG}/content_publishing_limit", fields="quota_usage,config")
    print("Quota de publication :", json.dumps(lim.get("data", lim))[:200])
    if LIEU:
        try:
            print("Lieu :", json.dumps(appel("GET", LIEU, fields="name,location")))
        except Exception as e:
            print("Lieu illisible avec ce token (il sera quand même essayé à la publication) :", str(e)[:200])
    # 08.11 : le vrai test d'écriture : préparer un post (conteneur) SANS le publier (rien n'apparaît sur le compte, il expire seul en 24 h)
    try:
        cal = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendrier.json")))
        img = cal[0]["i"][0]
        c = appel("POST", f"{IG}/media", image_url=IMAGES + urllib.parse.quote(img), caption="test")["id"]
        print("Écriture OK : post préparé sans être publié (", c, ")")
    except Exception as e:
        print("ÉCHEC écriture : Instagram refuse de préparer un post :", str(e)[:300]); sys.exit(1)
    print("OK : le robot peut publier sur ce compte.")


def simuler():
    """08.11 : la répétition générale du post du jour : tout est préparé chez Instagram (images, légende, lieu, story),
    SANS appuyer sur « publier ». Rien n'apparaît sur le compte ; les posts préparés expirent seuls en 24 h."""
    cal = json.load(open(os.path.join(ICI, "calendrier.json"), encoding="utf-8"))
    auj = datetime.datetime.now(TZ).date().isoformat()
    p = next((x for x in cal if x.get("d") == auj and x.get("auto")), None) or next((x for x in cal if x.get("d", "") >= auj and x.get("auto")), None)
    if not p:
        print("Aucun post prévu."); return
    legende = (p["l"].strip() + "\n\n" + p["g"].strip()).strip()
    print(f"Post : {p['d']} à {p['auto']} · {p['t']} · {len(p['i'])} image(s) · {len(legende)} caractères · {p['g']}")
    def conteneur(**k):
        c = appel("POST", f"{IG}/media", **k)["id"]; attendre(c); return c
    if len(p["i"]) == 1:
        try:
            conteneur(image_url=IMAGES + urllib.parse.quote(p["i"][0]), caption=legende, location_id=LIEU)
            print("Image, légende et lieu (Prilly) : OK")
        except Exception as e:
            print("Lieu refusé (le post partira sans lieu) :", str(e)[:160])
            conteneur(image_url=IMAGES + urllib.parse.quote(p["i"][0]), caption=legende)
            print("Image et légende : OK")
    else:
        enfants = []
        for n in p["i"][:10]:
            enfants.append(conteneur(image_url=IMAGES + urllib.parse.quote(n), is_carousel_item="true"))
            print("  image OK :", n)
        try:
            conteneur(media_type="CAROUSEL", children=",".join(enfants), caption=legende, location_id=LIEU)
            print("Carrousel, légende et lieu (Prilly) : OK")
        except Exception as e:
            print("Lieu refusé (le post partira sans lieu) :", str(e)[:160])
            conteneur(media_type="CAROUSEL", children=",".join(enfants), caption=legende)
            print("Carrousel et légende : OK")
    nom = f"{p['d']}_story.jpg"
    if os.path.exists(os.path.join(ICI, "stories", nom)):
        conteneur(image_url=STORIES + nom, media_type="STORIES")
        print("Story : OK")
    print("SIMULATION RÉUSSIE : tout est prêt, seul le bouton « publier » n'a pas été appuyé.")


if __name__ == "__main__":
    if os.environ.get("MODE") == "simulation" or "--simuler" in sys.argv:
        simuler()
    elif "--verifier" in sys.argv or os.environ.get("MODE") == "verifier":
        verifier()
    elif "--rafraichir" in sys.argv:
        rafraichir()
    else:
        main()
