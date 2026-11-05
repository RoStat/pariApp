# CHANGELOG

Tout changement de nom de champ dans `data/*.json` ou `journal/tickets.csv` est noté ici (contrat de données lu par l'appli et par l'agent Claude).

## 2026-11-05 — v2 (cahier des charges pariApp v1)

### Relais (`main`)
- `data/summary.json` : nouveau fichier, lu en premier par l'agent (`offer_created_at, fetched_at, next_followed_kickoffs, credits_remaining, picks_count, last_error…`).
- `data/offre.json` : champs ajoutés `offer_created_ts`, `boost` (grille Combi Boosté et limites de l'offre). Les événements « Multiplex » (sans marché 1/N/2) sont exclus.
- `data/followed_matches.json` : champs ajoutés `home, away, comp`. Nouveau `data/followed_history.json` (mémoire 10 jours pour le règlement des résultats).
- `data/value.json` : inchangé (champ `event_id` désormais présent dès la création de la ligne).
- `data/state.json` : `last_error` ajouté ; un run forcé (`--force`) n'y écrit plus rien.
- `config.json` : fenêtres `pre` [55, 85] et `close` [1, 15] (ex-[60, 80] et [1, 12], voir `_fenetres_verifiees`) ; sections `repo`, `scores`, `weekly`, `alias_issue` ; `odds_api.monthly_budget`.
- `fetch_offre.py` : 3 essais, sortie 0 si FDJ indisponible (`summary.fetch_error`).
- `odds_ref.py` : 401/403/429/réseau -> `state.last_error` + `summary.odds_error`, sortie 0.
- Nouveaux scripts : `scores.py` (règlement G/P), `weekly.py` (`journal/weekly.md`), `alias_issue.py` (Issue « alias manquants »).
- Tests : `tests/test_matching.py`, `test_devig.py`, `test_windows.py`, `test_scores.py` (lancés par le workflow en `workflow_dispatch` uniquement).
- Workflow : crons `0 8 * * *` (résultats) et `20 6 * * 1` (hebdo) ajoutés ; permission `issues: write` ; push avec rebase et 3 essais.

### Appli (`gh-pages`)
- PariApp v2 : lit `offre.json` + `value.json` + `summary.json` (plus de sql.js ni de fichier à choisir). Style « Discipliné », badges value, TRJ effectif, bonus Combi Boosté, plafond hebdomadaire, export CSV au format `journal/tickets.csv`.
