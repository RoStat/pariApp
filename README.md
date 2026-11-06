# pariApp — relais de données et appli Parions Sport point de vente

Deux branches, deux rôles :

- **`main` : le relais.** Un run GitHub Actions « journée » (trois jobs séquentiels, `scripts/boucle.py`) télécharge l'offre Parions Sport point de vente (FDJ) toutes les 30 min (10 min à l'approche d'un match suivi), relève les cotes Pinnacle (The Odds API) à deux instants par match suivi, calcule la valeur FDJ vs référence, relève blessés / suspendus / compos (API-Football), règle les résultats et tient un journal. Il ne commite que des JSON légers dans `data/` et `journal/`.
- **L'agent compositeur (tâche planifiée Claude Code, 17h27 Paris, 12h27 le week-end)** lit ces JSON, vérifie la disponibilité des joueurs, compose les tickets, les fait valider par `scripts/check_tickets.py` (une sélection par match, pas de couverture, pas de joueur absent, deadline) et commite `data/tickets.json`. Procédure : `docs/COMPOSER.md`.
- **`gh-pages` : PariApp v2.** Une page web mobile (`index.html` + `app.js` + `style.css`, sans build) qui affiche les tickets du jour (lien panier `adj.st`, case « validé », export du journal) et garde un générateur local en secours.

Chaîne : relais (données) → scoring (valeur Pinnacle, disponibilité) → Claude compose → script vérifie → appli affiche → tu valides.

```
.github/workflows/pariapp.yml        run « journée » : 3 jobs (07:00–12:30, 12:30–18:00, 18:00–21:30 UTC) qui bouclent ; cron de secours chaque heure
.github/workflows/pariapp-manuel.yml résultats 08:00 UTC, hebdo le lundi, Run workflow (tests + passage forcé)
config.json                     compétitions suivies, fenêtres de relevé, budget, boucle, dispo (API-Football), tickets (commentaires = clés _)
docs/COMPOSER.md                procédure de l'agent compositeur (tâche planifiée Claude Code)
scripts/boucle.py               boucle d'une tranche : offre -> Pinnacle -> dispo -> CLV -> alias -> commit, cadence 30/10 min
scripts/commit_push.sh          commit rejoué sur la pointe de la branche (pas de rebase : deux runs croisés ne se bloquent plus)
scripts/dispo.py                API-Football -> data/dispo.json (absents, compos officielles), budget 80 req/jour
scripts/check_tickets.py        vérifie et complète data/tickets.json contre l'offre, dispo.json et value.json
scripts/common.py               normalisation des noms, appariement, dévig, Kelly, summary.json
scripts/fetch_offre.py          zip FDJ -> data/offre.json (+ avis Pronosoft à < 48 h), followed_matches.json, followed_history.json
scripts/odds_ref.py             Pinnacle dans les fenêtres pre/close -> snapshots, value.json, unmatched.json
scripts/clv.py                  CLV des sélections du journal avec les relevés de clôture
scripts/scores.py               règlement G/P des sélections du journal (08h UTC, coupe-circuit crédits)
scripts/weekly.py               journal/weekly.md chaque lundi
scripts/alias_issue.py          Issue GitHub « Alias manquants » créée / mise à jour / fermée automatiquement
data/teams.json                 alias FDJ -> The Odds API (à compléter quand l'Issue le signale)
journal/tickets.csv             tes tickets (export de l'appli), resultat rempli par scores.py ; clv.csv et weekly.md générés
tests/                          matching, devig, windows (boucle), scores, dispo, check_tickets + mocks (sans réseau)
```

## Mise en route : les 5 gestes manuels

Tout le reste est fait par le workflow ou par l'agent.

0. **Disponibilité des joueurs** : `scripts/dispo.py` est prêt pour API-Football (secret `APIFOOTBALL_KEY`), mais **le plan gratuit ne sert pas la saison en cours** (vérifié le 06/11/2026 : « Free plans do not have access to this season, try from 2022 to 2024 »). Le script le détecte, cesse d'appeler l'API pour la journée et l'écrit dans `summary.dispo_error`. Tant qu'aucune source structurée gratuite n'est branchée, la disponibilité repose sur l'avis Pronosoft (`offre.json > avis`) et sur la recherche web que fait l'agent compositeur pour chaque match avec un pari joueur (`docs/COMPOSER.md` §2). Un plan API-Football payant (≈ 19 $/mois) activerait `dispo.json` sans autre changement.
1. **Clé The Odds API** (gratuite, 500 crédits/mois, e-mail requis) sur [the-odds-api.com](https://the-odds-api.com), puis sur GitHub : *Settings → Secrets and variables → Actions → New repository secret* `ODDS_API_KEY`. La clé n'est jamais écrite ailleurs.
2. **Visibilité du dépôt** : *Settings → General → Danger zone → Change visibility → Public*. Les minutes Actions sont alors gratuites (en privé, la cadence consomme ≈ 1 500 des 2 000 min offertes par mois : passer le cron du soir à `*/15`). L'offre FDJ est une donnée publique ; la clé reste secrète.
3. **GitHub Pages** : *Settings → Pages → Build and deployment → Source : Deploy from a branch → Branch `gh-pages` / `/ (root)`*. Ne pas choisir `main` : chaque commit du relais déclencherait un build. URL de l'appli : **https://rostat.github.io/pariApp/** (à ajouter à l'écran d'accueil du téléphone).
4. **Premier relevé réel** : onglet *Actions → pariapp-manuel → Run workflow* avec `force = pre`. Lire le résumé du job : événements API, appariés, crédits restants, `dispo`. Puis tester un lien « Ouvrir dans Parions Sport » depuis le téléphone et vérifier le panier.

Ensuite, les soirs où tu joues : bouton « Exporter le journal » dans l'appli, coller le CSV à la suite de `journal/tickets.csv` (jusqu'à ce qu'une automatisation sûre existe, voir D4).

## Budget de crédits The Odds API (≤ 300 / mois)

| Appel | Coût | Quand |
| --- | --- | --- |
| `/odds` (`h2h,totals`, région `eu`) | 2 crédits par compétition | fenêtres `early` (170–250 min avant le coup d'envoi, référence du jour pour l'agent compositeur), `pre` (55–85 min) et `close` (1–15 min) des matchs suivis, une fois par (compétition, créneau de 15 min, fenêtre) |
| `/scores?daysFrom=3` | 2 crédits par compétition (doc API, vérifiée le 05/11/2026) | 08h UTC, uniquement les compétitions qui ont des sélections en attente dans le journal |

Ordre de grandeur : 3 relevés × 2 crédits × 4 compétitions = 24 crédits par journée de match ; semaine européenne + un week-end de L1 ≈ 90 ; mois ≈ 300–350 avec le règlement des résultats (plafond gratuit 500).

Garde-fous : aucun appel hors fenêtre (`data/state.json` mémorise les créneaux relevés) ; arrêt sous `odds_api.min_credits_remaining` (50) ; un `Run workflow` forcé consomme des crédits mais n'écrit rien dans `state.json` (les crédits restants vont dans `summary.json`) ; le règlement des résultats se coupe seul si les crédits restants passent sous 120 avant le 20 du mois (`summary.scores_enabled = false`, raison dans `scores_disabled_reason`).

## Fenêtres de relevé et planification

GitHub n'exécute pas les crons de façon fiable (le 05/11/2026 : 4 runs sur ~55 attendus, aucun entre 15h10 et 21h26 UTC, donc aucun relevé Pinnacle en fenêtre). Le relais ne dépend donc plus des crons : un run « journée » (`pariapp.yml`) enchaîne trois jobs qui bouclent jusqu'à la fin de leur tranche (07:00–12:30, 12:30–18:00, 18:00–21:30 UTC ; moins de 6 h chacun, limite GitHub). Cadence : 30 min ; 10 min dès qu'un match suivi est à moins de 100 min du coup d'envoi, ce qui garantit un passage dans chaque fenêtre `pre` [55, 85] et `close` [1, 15] (vérifié par `tests/test_windows.py` pour des départs à n'importe quelle minute entre 07:00 et 13:00 UTC). Un cron de secours part chaque heure (`13 7-21`) : si le run du jour tourne, le nouveau attend puis sort aussitôt (les runs « annulés » dans l'onglet Actions sont ces doublons, pas des échecs) ; si le run a été perdu ou a planté, le suivant reprend la journée. Gratuit en dépôt public (≈ 14 h de runner par jour).

Les passages ponctuels (résultats 08:00 UTC, hebdo le lundi, Run workflow) sont dans `pariapp-manuel.yml`, groupe de concurrence distinct.

## Contrat de données (lu par l'appli et par l'agent `/pariapp`)

Tous les fichiers sont servis en clair par `https://raw.githubusercontent.com/RoStat/pariApp/main/data/<fichier>` (CORS `*`, cache CDN ≈ 5 min ; ajouter `?t=<timestamp>` pour forcer). Ordre de lecture conseillé : `summary.json` → `value.json` → `offre.json`. Horodatages en ISO 8601 UTC, `*_ts` en secondes Unix. Tout renommage de champ est noté dans `CHANGELOG.md`.

### `data/summary.json` — état du relais (≈ 2 Ko, mis à jour à chaque passage)

| Champ | Sens |
| --- | --- |
| `offer_created_at`, `fetched_at` | heure de l'offre FDJ (`info.created_ts`) et heure du relais |
| `events_count`, `followed_count` | matchs exportés / matchs des compétitions suivies |
| `next_followed_kickoffs[]` | `{match, comp, start, fin}` des 12 prochains matchs suivis (`fin` = fin de validation = coup d'envoi − 5 min) |
| `last_snapshot_at`, `last_snapshot_kind` | dernier relevé Pinnacle (`pre` ou `close`) |
| `credits_remaining`, `credits_used` | compteur The Odds API (en-têtes `x-requests-*`) |
| `picks_count`, `value_rows`, `unmatched_followed` | sélections au-dessus du seuil de valeur, lignes évaluées, matchs suivis non appariés |
| `fetch_error`, `odds_error`, `scores_error`, `last_error` | dernière erreur par étape (`null` si aucune) ; `last_error` = la première non nulle |
| `scores_enabled`, `scores_disabled_reason`, `scores_last_run`, `scores_settled`, `scores_pending` | règlement automatique des résultats |
| `updated_at` | heure d'écriture |

```json
{"offer_created_at": "2026-11-05T14:17:29Z", "fetched_at": "2026-11-05T14:35:42Z", "events_count": 92, "followed_count": 44,
 "next_followed_kickoffs": [{"match": "Aarhus GF-Braga", "comp": "Europa Conf.", "start": "2026-11-05T17:45:00Z", "fin": "2026-11-05T17:40:00Z"}],
 "last_snapshot_at": "2026-11-05T18:35:12Z", "last_snapshot_kind": "pre", "credits_remaining": 482, "credits_used": 18,
 "picks_count": 4, "value_rows": 120, "unmatched_followed": 0, "fetch_error": null, "odds_error": null, "scores_error": null, "last_error": null,
 "scores_enabled": true, "scores_disabled_reason": null, "updated_at": "2026-11-05T18:35:12Z"}
```

### `data/value.json` — sélections FDJ évaluées vs Pinnacle (≈ 20–60 Ko, à chaque relevé)

`{updated_at, min_value_pct, rows: [...], picks: [...]}` ; `picks` = les lignes de `rows` dont `value_pct ≥ min_value_pct`. Lignes triées par valeur décroissante ; les matchs dont la validation est fermée sont purgés à chaque passage. Marchés évalués : `1/N/2`, `Double chance` (dérivée), `Plus/Moins 2,5`.

| Champ | Sens |
| --- | --- |
| `event_id`, `match`, `comp`, `start`, `fin_ts` | match FDJ, coup d'envoi, fin de validation |
| `market`, `pick` | libellés FDJ (`1/N/2` → `1`/`N`/`2` ; `Double chance` → `1/N`/`N/2`/`1/2` ; `Plus/Moins 2,5` → `Plus 2.5`/`Moins 2.5`) |
| `cote_fdj`, `p_juste`, `cote_juste` | cote FDJ, probabilité dévigée de la référence, 1/p |
| `value_pct` | `100 × (p_juste × cote_fdj − 1)` |
| `mise_pct_bankroll` | ¼ Kelly plafonné à 2 % |
| `market_id`, `pos`, `lien` | identifiants du bouton FDJ et lien `adj.st` prêt à ouvrir |
| `reference`, `snapshot` | bookmaker source (`pinnacle`, sinon `winamax_fr`/`unibet_fr`) et fenêtre (`pre`/`close`) |

```json
{"event_id": 1302264, "match": "Leverkusen-Marseille", "comp": "Europa League", "start": "2026-11-05T20:00:00Z", "fin_ts": 1793908500,
 "market": "1/N/2", "pick": "N", "cote_fdj": 6.5, "p_juste": 0.1784, "cote_juste": 5.61, "value_pct": 15.95, "mise_pct_bankroll": 0.72,
 "market_id": 34625255, "pos": 2, "lien": "https://33xb.adj.st/betslip?bet_type=1&market_id=34625255,2&adj_t=1toqzbnl&pr=0",
 "reference": "pinnacle", "snapshot": "pre"}
```

### `data/offre.json` — l'offre FDJ utile (≈ 160 Ko, toutes les 30 min)

```
fetched_at, offer_created_at, offer_created_ts, link_template, comps{comp_id: nom},
boost{enabled, min_cote, grid_pct{"4": 2.0, …, "12": 25.0}, additional_winning_limit, min_stake, max_win},
events[] : {event_id, match, home, away, comp_id, comp, sport_key, followed, start, start_ts, fin_ts, avis (texte Pronosoft, matchs à < 48 h), markets{
   1N2{market_id, outcomes[{pos, lib, cote}]}, DC{…}, OU25{…}, BTTS{…},
   team_totals[{team, line, market_id, outcomes}], buteur{…}, double{…}, decisif{…}, double_match{…} }}
```
Lien panier : `https://33xb.adj.st/betslip?bet_type=1&market_id=<market_id>,<pos>&market_id=…&adj_t=1toqzbnl&pr=0` (une sélection par match ; `pos` = bouton). Marchés joueurs limités aux 5 premières cotes. Compétitions : les 4 suivies (LdC, LE, Conf., L1) + Ligue 2, Premier League, LaLiga, Serie A, Bundesliga (non suivies : pas de référence Pinnacle). Horizon : 7 jours ; événements « Multiplex » exclus.

### `data/dispo.json` — disponibilité des joueurs (API-Football, à chaque passage)

`{updated_at, status: ok|no_key|error, error, requests_today, budget, matches{event_id: {match, comp, start, fixture_id, home{team, absents[{player, type, reason}], xi, bench, formation}, away{…}, injuries_at, lineups_at}}, unmatched[]}`. `type` = `Missing Fixture` (absent) ou `Questionable` (incertain). `xi`/`bench` sont `null` tant que les compos officielles ne sont pas publiées (≈ 1 h avant le coup d'envoi : trop tard pour le point de vente, utile pour l'historique). `summary.json` reprend `dispo_status`, `dispo_matches`, `dispo_requests_today`, `dispo_error`.

### `data/tickets.json` — tickets du jour (agent compositeur, vérifiés)

`{generated_at, offer_created_at, author, params{nb, mise, gmin, gmax}, notes[], exclusions[{match, player, reason}], tickets[], check{ok, errors[], warnings[], checked_at}}` ; chaque ticket : `{id, name, style, story, legs[{event_id, match, comp, start, start_ts, fin_ts, mk, market, pick, type, label, market_id, pos, cote, player, value_pct, why}], cote, mise, gain, boost, trj, deadline, deadline_ts, link, key, checks{one_per_match, no_hedge, dispo: ok|warn|unknown}}`. `type` et `market` suivent les conventions de l'appli et du journal. Fichier absent = pas de tickets ce jour. Contrat d'entrée (ce que l'agent écrit) : `docs/COMPOSER.md`.

### `journal/tickets.csv`

Séparateur `;`, en-tête `date;ticket;event_id;match;market;pick;market_id;pos;cote_prise;mise;resultat`. C'est exactement ce que produit « Exporter le journal » dans l'appli. `resultat` = `G`/`P`, rempli par `scores.py` pour `1/N/2`, `Double chance`, `Plus/Moins 2,5` (les autres marchés restent à régler à la main). `clv.csv` ajoute `cote_cloture_juste` et `clv_pct`.

## PariApp v2 (branche `gh-pages`)

Accueil : carte « Tickets du jour (Claude) » quand `data/tickets.json` contient des tickets encore jouables (heure de génération, deadline, bouton « Voir les tickets »), sinon « Composer moi-même ». Écran Tickets du jour : nom, histoire, cote, bonus, gain, TRJ, deadline, jambes avec justification, lien FDJ, case « validé », export du journal, joueurs écartés et avertissements du vérificateur. Pas de régénération : les tickets sont vérifiés côté serveur.

Parcours du générateur local (secours) : Accueil (état des données, prochains coups d'envoi, budget hebdo) → Périmètre → Compétitions (LdC, LE, Conf., L1 pré-cochées, mémorisé) → Réglages (tickets, mise, gains, style Mélange / Safe / Risqué / Discipliné, plafond hebdomadaire) → Matchs (badge *value*) → Tickets (cote, bonus Combi Boosté, gain, **TRJ effectif**, deadline, lien FDJ, case « validé » mémorisée, régénérer, retirer une jambe, copier, exporter le journal).

Règles codées : une sélection par match et par ticket ; 12 sélections max ; un match dont la validation ferme dans moins de 45 min est exclu ; bandeau si l'offre a plus de 60 min ou si `summary.last_error` est renseigné ; TRJ effectif = produit des TRJ par marché (objet `TRJ` dans `app.js`) × multiplicateur du bonus ; préférence de tirage pour les jambes à valeur positive. Style Discipliné : 2–3 sélections, marchés 1N2 / double chance / +−2,5 / les 2 marquent, cote totale 3–8.

Test local : servir le dossier et ouvrir `index.html?data=http://localhost:8000/data/` avec une copie de `data/`.

## Automatisations

- **D1 Issue « Alias manquants (data/teams.json) »** (label `alias`) : créée ou mise à jour à chaque passage où un match suivi à moins de 36 h n'est pas apparié ; fermée seule quand la liste est vide.
- **D2 Règlement des résultats** : 08h UTC, `scores.py`, coupe-circuit décrit plus haut.
- **D3 `journal/weekly.md`** : lundi 06h20 UTC, une section par semaine ISO (tickets, mises, P&L, CLV, crédits).
- **D4 (abandonné)** : accepter le CSV de l'appli par `repository_dispatch` exigerait un token GitHub côté page publique. Sécurité avant confort : le journal se colle à la main.

## Tests

```
python3 -m unittest discover -s tests -v
python3 scripts/fetch_offre.py --zip <zip FDJ>
python3 scripts/odds_ref.py --mock tests/mock_odds.json --force pre
python3 scripts/dispo.py --mock tests/mock_apifootball.json
python3 scripts/check_tickets.py data/tickets.json
python3 scripts/scores.py --mock tests/mock_scores.json
python3 scripts/clv.py && python3 scripts/weekly.py && python3 scripts/alias_issue.py --dry-run
DRY_RUN=1 python3 scripts/boucle.py --once        # un passage complet sans push
```
Python 3.12, bibliothèque standard + `requests`. Le workflow lance les tests uniquement sur `workflow_dispatch`.

## Limites connues

- Les cotes Pinnacle de The Odds API viennent du site public avec quelques minutes de délai : bien pour l'avant-match et la clôture, pas pour chasser des mouvements.
- Lire les cotes Pinnacle est légal ; y parier depuis la France ne l'est pas (opérateur non agréé ANJ). Rien ici n'envoie vers Pinnacle.
- L'appariement repose sur les noms d'équipes : l'Issue `alias` guide les premiers ajouts dans `teams.json`.
- GitHub ne garantit ni l'heure ni l'exécution des crons : la boucle journée s'en affranchit tant qu'un cron de secours part dans la journée ; un run qui démarre après la fenêtre `pre` d'un match de début d'après-midi ne la rattrape pas.
- Les compos officielles sortent ≈ 1 h avant le coup d'envoi et il faut 45 min pour aller scanner : la disponibilité se juge sur les absents connus la veille (blessés, suspendus), pas sur la compo.
- L'agent compositeur n'est pas infaillible : `check_tickets.py` bloque les erreurs mécaniques (bouton inexistant, couverture, joueur déclaré absent), pas un mauvais jugement sportif.
- Le TRJ point de vente est plafonné à 76,5 % ; un combiné multiplie les marges (5 jambes 1N2 ≈ 43 % de retour). L'outil organise, il ne crée pas d'avantage : l'espérance reste négative. Rien ne se conclut du CLV avant 200 sélections.
