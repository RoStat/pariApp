"""Fonctions partagées : config, chemins, normalisation des noms d'équipes, appariement, dévig."""
import json, re, unicodedata, difflib, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "data"
OFFRE_DIR = ROOT / "offre"
SNAP_DIR = DATA / "snapshots"
JOURNAL = ROOT / "journal"
ADJ_T = "1toqzbnl"

STOP = {"fc", "ac", "sc", "cf", "sk", "fk", "ks", "nk", "sv", "as", "afc", "cd", "ud", "if", "bk", "ssc", "sl", "rsc",
        "kaa", "1907", "1999", "04", "05", "club", "de", "the", "cp", "utd", "united"}
REPL = {"man.": "manchester", "st ": "saint ", "st.": "saint", "ath.": "athletic", "atl.": "atletico", "uni.": "universitatea",
        "hap.": "hapoel", "mac.": "maccabi", "ein.": "eintracht", "m'gladbach": "monchengladbach", "nottingham f.": "nottingham forest"}


def now_ts() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M")


def norm(name: str) -> str:
    """'Man. City' -> 'manchester city' ; 'FC Copenhague' -> 'copenhague'. Sert à comparer deux libellés."""
    s = name.lower().strip()
    for a, b in REPL.items():
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks) or s.strip()


def load_aliases() -> dict:
    raw = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def team_match_score(fdj: str, api: str, aliases: dict) -> float:
    """1.0 = alias déclaré ou égalité normalisée ; sinon ratio difflib sur les formes normalisées."""
    if api in aliases.get(fdj, []):
        return 1.0
    a, b = norm(fdj), norm(api)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a) and min(len(a), len(b)) >= 5:
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
