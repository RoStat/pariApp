#!/usr/bin/env python3
"""Issue GitHub « alias manquants » (D1) : à chaque passage, si data/unmatched.json liste des matchs suivis à moins de 36 h
sans correspondance The Odds API, crée ou met à jour une Issue unique (titre fixe, label `alias`) avec
`match FDJ -> meilleur candidat API (score)`. La ferme quand la liste est vide. API REST via `gh api` (présent sur
ubuntu-latest), GH_TOKEN = github.token (permission issues: write). Toute erreur est affichée et ignorée (code 0).

Usage : GH_TOKEN=... GITHUB_REPOSITORY=owner/repo python3 scripts/alias_issue.py [--dry-run]
"""
import os, sys, json, argparse, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, load_json, iso, now_ts

CFG = CONFIG["alias_issue"]


def api(method: str, path: str, payload: dict | None = None):
    cmd = ["gh", "api", "-X", method, path]
    if payload is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return json.loads(r.stdout) if r.stdout.strip() else None


def body_for(rows: list) -> str:
    lines = [f"Matchs FDJ suivis à moins de {CFG['horizon_hours']} h sans correspondance The Odds API (passage du {iso(now_ts())}).",
             "Pour chaque ligne : ajouter dans `data/teams.json` l'alias `\"<équipe FDJ>\": [\"<nom API>\"]` pour l'équipe qui diffère,",
             "ou corriger `common.norm()` si le motif est récurrent. L'issue se ferme seule quand la liste est vide.", "",
             "| Match FDJ | Coup d'envoi (UTC) | Meilleur candidat API | Score |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['match']} | {r['start']} | {r.get('best_api') or '—'} | {r.get('score', 0):.2f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche le corps de l'issue sans appeler GitHub")
    a = ap.parse_args()
    rows = load_json(DATA / "unmatched.json", {}).get("rows", [])
    if a.dry_run:
        print(body_for(rows) if rows else "liste vide : l'issue serait fermée")
        return 0
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        print("GH_TOKEN absent : pas d'Issue (exécution locale)")
        return 0
    repo = os.environ.get("GITHUB_REPOSITORY") or f"{CONFIG['repo']['owner']}/{CONFIG['repo']['name']}"
    try:
        existing = [i for i in (api("GET", f"repos/{repo}/issues?labels={CFG['label']}&state=open&per_page=20") or []) if i.get("title") == CFG["title"]]
        if not rows:
            for i in existing:
                api("POST", f"repos/{repo}/issues/{i['number']}/comments", {"body": f"Liste vide au passage du {iso(now_ts())} : tous les matchs suivis sont appariés."})
                api("PATCH", f"repos/{repo}/issues/{i['number']}", {"state": "closed", "state_reason": "completed"})
                print(f"issue #{i['number']} fermée")
            if not existing:
                print("aucun alias manquant, aucune issue ouverte")
            return 0
        body = body_for(rows)
        if existing:
            api("PATCH", f"repos/{repo}/issues/{existing[0]['number']}", {"body": body})
            print(f"issue #{existing[0]['number']} mise à jour ({len(rows)} matchs)")
        else:
            try:
                api("POST", f"repos/{repo}/labels", {"name": CFG["label"], "color": "FBCA04", "description": "Alias d'équipe à ajouter dans data/teams.json"})
            except RuntimeError:
                pass  # label déjà présent
            out = api("POST", f"repos/{repo}/issues", {"title": CFG["title"], "labels": [CFG["label"]], "body": body})
            print(f"issue créée : {out.get('html_url')} ({len(rows)} matchs)")
    except Exception as e:  # noqa: BLE001
        print(f"alias_issue : {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
