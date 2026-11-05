# pariApp — relais de données et appli Parions Sport point de vente

Deux branches, deux rôles :

- **`main` : le relais.** Un workflow GitHub Actions télécharge l'offre Parions Sport point de vente (FDJ) toutes les 30 min, relève les cotes Pinnacle (The Odds API) à deux instants par match suivi, calcule la valeur FDJ vs référence, règle les résultats et tient un journal. Il ne commite que des JSON légers dans `data/` et `journal/`.
- **`gh-pages` : PariApp v2.** Une page web mobile (`index.html` + `app.js` + `style.css`, sans build) qui lit ces JSON, génère des tickets combinés, affiche leur TRJ effectif et ouvre le panier dans l'appli FDJ via un lien `adj.st`.

Le skill Claude `/pariapp` lit les mêmes fichiers (section « Contrat de données »).

```
.github/workflows/pariapp.yml   planification (UTC), tests sur lancement manuel, commit automatique
config.json                     compétitions suivies, fenêtres de relevé, budget, marchés exportés (commentaires = clés _)
scripts/common.py               normalisation des noms, appariement, dévig, Kelly, summary.json
scripts/fetch_offre.py          zip FDJ -> data/offre.json, followed_matches.json, followed_history.json
scripts/odds_ref.py             Pinnacle dans les fenêtres pre/close -> snapshots, value.json, unmatched.json
scripts/clv.py                  CLV des sélections du journal avec les relevés de clôture
scripts/scores.py               règlement G/P des sélections du journal (08h UTC, coupe-circuit crédits)
scripts/weekly.py               journal/weekly.md chaque lundi
scripts/alias_issue.py          Issue GitHub « Alias manquants » créée / mise à jour / fermée automatiquement
data/teams.json                 alias FDJ -> The Odds API (à compléter quand l'Issue le signale)
journal/tickets.csv             tes tickets (export de l'appli), resultat rempli par scores.py ; clv.csv et weekly.md générés
tests/                          test_matching, test_devig, test_windows, test_scores + mocks (sans réseau)
```

## Mise en route : les 4 gestes manuels

Tout le reste est fait par le workflow ou par l'agent.

1. **Clé The Odds API** (gratuite, 500 crédits/mois, e-mail requis) sur [the-odds-api.com](https://the-odds-api.com), puis sur GitHub : *Settings → Secrets and variables → Actions → New repository secret* `ODDS_API_KEY`. La clé n'est jamais écrite ailleurs.
2. **Visibilité du dépôt** : *Settings → General → Danger zone → Change visibility → Public*. Les minutes Actions sont alors gratuites (en privé, la cadence consomme ≈ 1 500 des 2 000 min offertes par mois : passer le cron du soir à `*/15`). L'offre FDJ est une donnée publique ; la clé reste secrète.
3. **GitHub Pages** : *Settings → Pages → Build and deployment → Source : Deploy from a branch → Branch `gh-pages` / `/ (root)`*. Ne pas choisir `main` : chaque commit du relais déclencherait un build. URL de l'appli : **https://rostat.github.io/pariApp/** (à ajouter à l'écran d'accueil du téléphone).
4. **Premier relevé réel** : onglet *Actions → pariapp-relais → Run workflow* avec `force = pre`. Lire le résumé du job : événements API, appariés, crédits restants. Puis tester un lien « Ouvrir dans Parions Sport » depuis le téléphone et vérifier le panier.

Ensuite, les soirs où tu joues : bouton « Exporter le journal » dans l'appli, coller le CSV à la suite de `journal/tickets.csv` (jusqu'à ce qu'une automatisation sûre existe, voir D4).

## Budget de crédits The Odds API (≤ 300 / mois)

| Appel | Coût | Quand |
| --- | --- | --- |
| `/odds` (`h2h,totals`, région `eu`) | 2 crédits par compétition | fenêtres `pre` (55–85 min avant le coup d'envoi) et `close` (1–15 min) des matchs suivis, une fois par (compétition, créneau de 15 min, fenêtre) |
| `/scores?daysFrom=3` | 2 crédits par compétition (doc API, vérifiée le 05/11/2026) | 08h UTC, uniquement les compétitions qui ont des sélections en attente dans le journal |

Ordre de grandeur : 2 relevés × 2 crédits × 4 compétitions = 16 crédits par journée de match ; semaine européenne + un week-end de L1 ≈ 60 ; mois ≈ 200–250 avec le règlement des résultats.

Garde-fous : aucun appel hors fenêtre (`data/state.json` mémorise les créneaux relevés) ; arrêt sous `odds_api.min_credits_remaining` (50) ; un `Run workflow` forcé consomme des crédits mais n'écrit rien dans `state.json` (les crédits restants vont dans `summary.json`) ; le règlement des résultats se coupe seul si les crédits restants passent sous 120 avant le 20 du mois (`summary.scores_enabled = false`, raison dans `scores_disabled_reason`).

## Fenêtres de relevé et cron

Crons (UTC) : `5,35 7-23 * * *` (offre toutes les 30 min) et `*/10 16-21 * * *` (soirée). `tests/test_windows.py` vérifie par calcul que, pour des coups d'envoi à 18h45 et 21h00 heure de Paris, été comme hiver, chaque fenêtre reçoit au moins un passage même avec 5 min de retard du cron. Le détail est dans `config.json` (`snapshots._fenetres_verifiees`). Limite connue : un retard de cron supérieur à 15 min fait perdre le relevé de clôture du match concerné.

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
events[] : {event_id, match, home, away, comp_id, comp, sport_key, followed, start, start_ts, fin_ts, markets{
   1N2{market_id, outcomes[{pos, lib, cote}]}, DC{…}, OU25{…}, BTTS{…},
   team_totals[{team, line, market_id, outcomes}], buteur{…}, double{…}, decisif{…}, double_match{…} }}
```
Lien panier : `https://33xb.adj.st/betslip?bet_type=1&market_id=<market_id>,<pos>&market_id=…&adj_t=1toqzbnl&pr=0` (une sélection par match ; `pos` = bouton). Marchés joueurs limités aux 5 premières cotes. Compétitions : les 4 suivies (LdC, LE, Conf., L1) + Ligue 2, Premier League, LaLiga, Serie A, Bundesliga (non suivies : pas de référence Pinnacle). Horizon : 7 jours ; événements « Multiplex » exclus.

### `journal/tickets.csv`

Séparateur `;`, en-tête `date;ticket;event_id;match;market;pick;market_id;pos;cote_prise;mise;resultat`. C'est exactement ce que produit « Exporter le journal » dans l'appli. `resultat` = `G`/`P`, rempli par `scores.py` pour `1/N/2`, `Double chance`, `Plus/Moins 2,5` (les autres marchés restent à régler à la main). `clv.csv` ajoute `cote_cloture_juste` et `clv_pct`.

## PariApp v2 (branche `gh-pages`)

Parcours : Accueil (état des données, prochains coups d'envoi, budget hebdo) → Périmètre → Compétitions (LdC, LE, Conf., L1 pré-cochées, mémorisé) → Réglages (tickets, mise, gains, style Mélange / Safe / Risqué / Discipliné, plafond hebdomadaire) → Matchs (badge *value*) → Tickets (cote, bonus Combi Boosté, gain, **TRJ effectif**, deadline, lien FDJ, case « validé » mémorisée, régénérer, retirer une jambe, copier, exporter le journal).

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
python3 scripts/scores.py --mock tests/mock_scores.json
python3 scripts/clv.py && python3 scripts/weekly.py && python3 scripts/alias_issue.py --dry-run
```
Python 3.12, bibliothèque standard + `requests`. Le workflow lance les tests uniquement sur `workflow_dispatch`.

## Limites connues

- Les cotes Pinnacle de The Odds API viennent du site public avec quelques minutes de délai : bien pour l'avant-match et la clôture, pas pour chasser des mouvements.
- Lire les cotes Pinnacle est légal ; y parier depuis la France ne l'est pas (opérateur non agréé ANJ). Rien ici n'envoie vers Pinnacle.
- L'appariement repose sur les noms d'équipes : l'Issue `alias` guide les premiers ajouts dans `teams.json`.
- GitHub ne garantit pas l'heure des crons ; un retard > 15 min fait perdre un relevé de clôture.
- Le TRJ point de vente est plafonné à 76,5 % ; un combiné multiplie les marges (5 jambes 1N2 ≈ 43 % de retour). L'outil organise, il ne crée pas d'avantage : l'espérance reste négative. Rien ne se conclut du CLV avant 200 sélections.
