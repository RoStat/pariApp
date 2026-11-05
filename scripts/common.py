"""Fonctions partagées : config, chemins, normalisation des noms d'équipes, appariement, dévig, Kelly, summary.json."""
import json, re, unicodedata, difflib, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "data"
OFFRE_DIR = ROOT / "offre"
SNAP_DIR = DATA / "snapshots"
JOURNAL = ROOT / "journal"
SUMMARY = DATA / "summary.json"
ADJ_T = "1toqzbnl"

# Jetons sans valeur discriminante (sigles de clubs, articles). "utd"/"united" sont retirés des deux côtés : "Leeds Utd" == "Leeds United".
STOP = {"fc", "sc", "cf", "sk", "fk", "ks", "nk", "sv", "afc", "cd", "ud", "if", "bk", "ssc", "sl", "rsc", "rc", "og", "kaa", "cs", "fsv",
        "vfb", "vfl", "tsg", "bsc", "aif", "1", "04", "05", "1899", "1907", "1999", "club", "de", "the", "cp", "fr", "ii", "and",
        "olympique", "stade", "royal", "royale", "albion"}
# Mots qui peuvent manquer d'un côté sans changer d'équipe : "Bayer Leverkusen" == "Leverkusen". "inter" n'y est pas : Inter Milan != AC Milan.
QUALIFIERS = {"bayer", "borussia", "union", "sporting", "real", "athletic", "deportivo", "racing", "eintracht", "werder", "hamburger",
              "hertha", "red", "bull", "dinamo", "dynamo", "lokomotiv", "spartak", "ac", "as", "belgrade", "town", "hove"}
# Abréviations FDJ -> forme longue (appliquées avant la translittération, sur la chaîne en minuscules).
REPL = {"man. city": "manchester city", "man. united": "manchester united", "man.": "manchester", "st ": "saint ", "st.": "saint",
        "ath.": "athletic ", "atl.": "atletico ", "uni.": "universitatea ", "hap.": "hapoel ", "mac.": "maccabi ", "ein.": "eintracht ",
        "m'gladbach": "monchengladbach", "nottingham f.": "nottingham forest", "utd": "united", "nimègue": "nijmegen", "copenhague": "copenhagen",
        "brême": "bremen", "francfort": "frankfurt", "turin": "", "milan ac": "ac milan", "séville": "sevilla", "barcelone": "barcelona",
        "varsovie": "warsaw", "prague": "praha", "athènes": "athens", "nicosie": "nicosia", "crète": "crete", "salzbourg": "salzburg",
        "fribourg": "freiburg", "mayence": "mainz", "cologne": "koln", "hambourg": "hamburg", "lisbonne": "lisbon", "gênes": "genoa",
        "naples": "napoli", "bologne": "bologna", "parme": "parma", "rome": "roma", "valence": "valencia", "la corogne": "deportivo la coruna",
        "etoile rouge": "red star", "lyonnais": "lyon", "rennais": "rennes", "marseillais": "marseille"}
# Lettres que NFKD ne décompose pas.
TRANSLIT = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ł": "l", "đ": "d", "ı": "i", "ð": "d", "þ": "th"})


def now_ts() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M")


def norm(name: str) -> str:
    """'Man. City' -> 'manchester city' ; 'FC Copenhague' -> 'copenhagen' ; 'Bodø/Glimt' -> 'bodo glimt'. Sert à comparer deux libellés."""
    s = name.lower().strip()
    for a, b in REPL.items():
        s = s.replace(a, b)
    s = s.translate(TRANSLIT)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks) or s.strip()


def load_aliases() -> dict:
    raw = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def team_match_score(fdj: str, api: str, aliases: dict) -> float:
    """1.0 = alias déclaré, égalité normalisée ou mêmes mots ; 0.92 = l'un contient l'autre (mots en plus = qualificatifs) ;
    sinon ratio difflib sur les formes normalisées (seuil d'appariement : 0.82)."""
    if api in aliases.get(fdj, []) or norm(api) in {norm(x) for x in aliases.get(fdj, [])}:
        return 1.0
    a, b = norm(fdj), norm(api)
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    if set(ta) == set(tb):
        return 1.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(" ".join(short)) >= 5 and " ".join(short) in " ".join(long_):
        extra = set(long_) - set(short)
        if len(short) >= 2 or extra <= QUALIFIERS:
            return 0.92
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_events(fdj_events: list, api_events: list, aliases: dict, max_minutes_gap: int = 20, min_score: float = 0.82):
    """Apparie chaque match FDJ (home, away, start_ts) à un événement The Odds API (home_team, away_team, commence_time).
    Retourne (pairs, unmatched) ; pairs = liste de (fdj_event, api_event, score)."""
    pairs, unmatched = [], []
    for e in fdj_events:
        best, best_score = None, 0.0
        for a in api_events:
            try:
                a_ts = dt.datetime.fromisoformat(a["commence_time"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if abs(a_ts - e["start_ts"]) > max_minutes_gap * 60:
                continue
            s = min(team_match_score(e["home"], a["home_team"], aliases), team_match_score(e["away"], a["away_team"], aliases))
            if s > best_score:
                best, best_score = a, s
        if best is not None and best_score >= min_score:
            pairs.append((e, best, round(best_score, 3)))
        else:
            unmatched.append({"match": e["match"], "start": iso(e["start_ts"]), "best_api": (best["home_team"] + " - " + best["away_team"]) if best else None, "score": round(best_score, 3)})
    return pairs, unmatched


def devig(prices: list, method: str = "proportional") -> list:
    """Cotes décimales d'un marché complet -> probabilités justes (somme 1). 'proportional' = marge répartie au prorata."""
    imp = [1.0 / p for p in prices]
    s = sum(imp)
    if method == "power":
        # résout sum(imp_i ** k) = 1 par dichotomie ; pénalise davantage les outsiders (biais favori-outsider)
        lo, hi = 0.5, 3.0
        for _ in range(60):
            k = (lo + hi) / 2
            tot = sum(p ** k for p in imp)
            lo, hi = (k, hi) if tot > 1 else (lo, k)
        return [p ** k for p in imp]
    return [p / s for p in imp]


def kelly_fraction(p: float, cote: float) -> float:
    """Fraction de bankroll (Kelly plein) ; négatif = pas de valeur."""
    b = cote - 1.0
    return (p * cote - 1.0) / b if b > 0 else -1.0


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (ValueError, OSError):
        return default


def read_summary() -> dict:
    return load_json(SUMMARY, {})


def update_summary(**fields) -> dict:
    """Fusionne des champs dans data/summary.json (lu en premier par l'agent Claude). Une clé à None est conservée telle quelle
    (ex. last_error: null = pas d'erreur)."""
    s = read_summary()
    s.update(fields)
    s["last_error"] = s.get("fetch_error") or s.get("odds_error") or s.get("scores_error") or None
    s["updated_at"] = iso(now_ts())
    DATA.mkdir(exist_ok=True)
    SUMMARY.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s
