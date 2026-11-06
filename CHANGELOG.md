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

## 2026-11-06 — v3 : boucle journée, disponibilité des joueurs, agent compositeur
### Relais (`main`)
- Planification : `pariapp.yml` devient un run « journée » en 3 jobs séquentiels qui bouclent (`scripts/boucle.py`, cadence 30/10 min), cron de secours horaire `13 7-21` ; `pariapp-manuel.yml` reprend résultats (08:00 UTC), hebdo et Run workflow. Cause : GitHub n'a exécuté que 4 crons sur ~55 le 05/11 (aucun relevé Pinnacle en fenêtre).
- Commit : `scripts/commit_push.sh` rejoue le commit sur la pointe de la branche (fetch + reset --soft + add + push, 4 essais) au lieu d'un `pull --rebase` ; checkout sur `ref` de la branche. Cause : deux runs retardés démarrés à 3 s d'écart le 06/11 01:46 UTC, conflit de rebase sur des JSON d'une ligne.
- `data/dispo.json` : nouveau (API-Football, secret `APIFOOTBALL_KEY` ; plan gratuit sans accès à la saison 2026-27, constaté le 06/11 : le script n'insiste pas, `status: error`) ; `summary.json` : champs `dispo_status`, `dispo_matches`, `dispo_requests_today`, `dispo_error`.
- `data/offre.json` : champ `avis` (texte de l'avis Pronosoft) sur les matchs à moins de 48 h (`offre_json.avis_hours`).
- `data/tickets.json` : nouveau, écrit par l'agent compositeur et vérifié/complété par `scripts/check_tickets.py` (contrat dans README et `docs/COMPOSER.md`).
- `data/state.json` : désormais commité (créneaux Pinnacle relevés, compteur API-Football) ; section `dispo`.
- `config.json` : sections `boucle`, `dispo`, `tickets` ; `offre_json.avis_hours`.
- Tests : `test_windows.py` réécrit pour la boucle ; nouveaux `test_dispo.py`, `test_check_tickets.py`, `tests/mock_offre.json`, `tests/mock_apifootball.json`.
### Appli (`gh-pages`)
- Carte et écran « Tickets du jour (Claude) » lisant `data/tickets.json` (validation, export journal, joueurs écartés, avertissements). Générateur local conservé en secours (« Composer moi-même »).
