# pariapp-relais

Relais de données pour PariApp et le skill `/pariapp` : offre Parions Sport point de vente toutes les 30 min, cotes Pinnacle (The Odds API) uniquement aux deux instants utiles, valeur FDJ vs référence, et CLV du journal.

```
.github/workflows/pariapp.yml   planification (UTC) + commit automatique
scripts/fetch_offre.py          zip FDJ -> data/offre.json (marchés utiles, market_id + pos pour les liens adj.st)
scripts/odds_ref.py             Pinnacle à H-60/80 et H-1/12 des matchs suivis, garde-fou crédits, value.json, snapshots
scripts/clv.py                  CLV des tickets de journal/tickets.csv avec les relevés de clôture
scripts/common.py               normalisation des noms, appariement, dévig, Kelly
config.json                     compétitions suivies, fenêtres, seuils, marchés exportés
data/teams.json                 alias FDJ -> The Odds API (à compléter quand data/unmatched.json le signale)
data/offre.json                 régénéré toutes les 30 min (≈150 Ko) — c'est le fichier que PariApp et le skill lisent
data/value.json                 sélections FDJ évaluées, triées par valeur ; `picks` = au-dessus du seuil
data/snapshots/                 un fichier par relevé Pinnacle (API brute + cotes FDJ du moment) : l'historique de clôture est à nous
journal/tickets.csv             tes tickets (saisie manuelle), journal/clv.csv produit par clv.py
```

## Mise en route (15 min)

1. Créer un dépôt **public** (les minutes GitHub Actions y sont gratuites ; l'offre FDJ est une donnée publique, la clé API reste en secret). En privé, la cadence ci-dessous consomme ~1 500 min/mois sur les 2 000 offertes : réduire à `*/15` le soir.
2. Copier ce dossier, `git push`.
3. Clé gratuite sur [the-odds-api.com](https://the-odds-api.com) (500 crédits/mois) → Settings → Secrets and variables → Actions → `ODDS_API_KEY`.
4. Onglet Actions → `pariapp-relais` → Run workflow avec `force = pre` : premier relevé réel. Vérifier `data/unmatched.json` et compléter `data/teams.json` pour les matchs non appariés (les noms exacts de The Odds API apparaissent dans `best_api` et dans le snapshot).
5. Noter les URL brutes pour PariApp et le skill :
   `https://raw.githubusercontent.com/<owner>/<repo>/main/data/offre.json` et `.../data/value.json`.

## Budget de crédits

- Un appel = `marchés × régions` crédits par compétition : `h2h,totals` en région `eu` = 2 crédits.
- Deux relevés par journée de match (pré-compos et clôture) × 4 compétitions suivies = 16 crédits par journée ; semaine européenne + un week-end de L1 ≈ 60 crédits ; mois ≈ 250 sur 500.
- Garde-fous : aucun appel hors fenêtre ; un seul relevé par (compétition, créneau de coup d'envoi, fenêtre) grâce à `data/state.json` ; arrêt sous `min_credits_remaining` (50). Un `Run workflow` forcé consomme des crédits et n'est pas mémorisé.
- Le zip FDJ est gratuit et illimité ; il n'est jamais versionné (`.gitignore`), seul `data/offre.json` l'est.

## Ce que calcule value.json

Pour chaque match apparié : probabilités justes = cotes Pinnacle (sinon Winamax/Unibet) dévigées au prorata ; valeur = p × cote FDJ − 1 ; mise suggérée = ¼ Kelly plafonné à 2 % de bankroll. Marchés couverts : 1/N/2, double chance (dérivée du 1/N/2), Plus/Moins 2,5. Les marchés joueurs FDJ (buteur, décisif…) sont exportés dans `offre.json` mais pas évalués : pas de référence fiable chez The Odds API en gratuit.

Lecture honnête : la plupart des lignes FDJ ressortent négatives (TRJ point de vente plafonné à 76,5 %). Les positives attendues : cotes boostées, double chance, retard FDJ après une info. `value.json` est un filtre, pas une promesse.

## Journal et CLV

`journal/tickets.csv` (séparateur `;`) : `date;ticket;event_id;match;market;pick;market_id;pos;cote_prise;mise;resultat`.
`event_id`, `market_id`, `pos` se copient depuis `value.json` ou `offre.json`. `market` ∈ {`1/N/2`, `Double chance`, `Plus/Moins 2,5`} pour que le CLV soit calculé ; `resultat` = `G`/`P`.
`clv.py` tourne à chaque passage : `clv_pct` = cote prise × probabilité juste de clôture − 1. Règle : rien ne se conclut avant 200 sélections.

## Limites connues

- Les cotes Pinnacle de The Odds API viennent du site public, avec un délai de quelques minutes : suffisant pour l'avant-match et la clôture, pas pour chasser des mouvements.
- Lire les cotes Pinnacle est légal ; y parier depuis la France ne l'est pas (opérateur non agréé ANJ).
- L'appariement repose sur les noms d'équipes : la première semaine demande quelques ajouts dans `teams.json`.
- Les horaires du workflow sont en UTC ; la plage `16-21` couvre 17h–23h heure de Paris été comme hiver.

## Tests sans réseau

```
python3 scripts/fetch_offre.py --zip tests/offre.zip
python3 scripts/odds_ref.py --mock tests/mock_odds.json --force pre
python3 scripts/clv.py
```
