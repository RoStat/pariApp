# Compositeur de tickets — procédure de l'agent Claude

Tâche planifiée Claude Code (17h27 Paris tous les jours, 12h27 samedi et dimanche). Le relais fournit les données,
**l'agent compose, le script vérifie**, l'appli affiche. Résultat : `data/tickets.json` sur `main`.

## 0. Préparer
```bash
git checkout main && git pull --ff-only origin main
python3 -m json.tool data/summary.json
```
Lire dans l'ordre : `data/summary.json` (état, erreurs, `credits_remaining`, `last_snapshot_at`), `data/offre.json` (matchs, marchés, `avis` Pronosoft,
`boost`), `data/value.json` (`rows` : valeur FDJ vs Pinnacle en %, `picks` ≥ 3 % ; le relevé `early` du jour est pris 3 à 4 h avant le coup d'envoi,
donc juste avant ce passage ; une ligne dont `snapshot`/`start` date d'un autre jour ne vaut rien), `data/dispo.json` (absents, compos ; `status`),
`config.json > tickets` (paramètres par défaut : nombre, mise, fourchette de gains, marge de scan).
Si `summary.last_error` ou `offre` de plus de 3 h : le dire dans `notes`, composer quand même si l'offre est exploitable.

## 1. Périmètre
Soirée = matchs dont `fin_ts` > maintenant + `marge_scan_min` (45 min) et coup d'envoi avant 05h00 Paris le lendemain.
Priorité aux compétitions suivies (`followed: true`) ; élargir aux autres compétitions de l'offre si moins de 6 matchs.
Le week-end à 12h27 : périmètre = l'après-midi et la soirée du jour.

## 2. Disponibilité des joueurs (règle absolue : aucun pari joueur non vérifié)
Pour chaque joueur envisagé (Buteur, Buteur 2 fois ou plus, Joueur décisif) :
1. `dispo.json > matches[event_id]` : `absents` (type `Missing Fixture` = exclu, `Questionable` = éviter), `xi`/`bench` quand les compos sont là.
2. `offre.json > events[].avis` (texte Pronosoft : « privés de X, suspendu », « amoindris par les blessures de… »).
3. Si le match n'est pas dans `dispo.json` (`status` ≠ `ok` ou non apparié) : une recherche web ciblée par match
   (« <équipe> compo probable <adversaire> » : L'Équipe, Maxifoot, Foot Mercato) pour confirmer que le joueur est dans le groupe et titulaire probable.
4. Sans confirmation : pas de jambe joueur sur ce match. Remplacer par un marché équipe (buts équipe, +/−2,5, les 2 marquent).
Noter chaque joueur écarté dans `exclusions` (match, joueur, raison, source).

## 3. Choisir les sélections
- Jambes « masse » : favoris 1,15–1,70, double chance 1,15–1,65, buts équipe +1,5, +/−2,5 ≤ 1,75, les 2 marquent ≤ 1,80.
- Jambes « piquantes » (1–2 par ticket) : nul 3–4,3, outsider 2,4–4,6, doublé ≤ 4,6 d'un joueur vérifié titulaire et premier buteur attendu.
- Privilégier les sélections à `value_pct` ≥ 0 (surtout `picks`) ; éviter `value_pct` < −8 (FDJ nettement surcotée). Un marché sans
  référence (joueurs, buts équipe) se juge sur la cote, l'avis et le contexte, pas sur une intuition de score.
- Cohérence interne : pas de « Moins 2,5 » avec un doublé ou « les 2 marquent » du même match (impossible de toute façon : une sélection
  par match et par ticket) ; entre tickets, jamais deux choix incompatibles sur un même match (1 contre N, Plus contre Moins…), ≤ 2 matchs
  communs entre deux tickets (de préférence avec des marchés différents : 1N2 dans l'un, buts équipe dans l'autre), un joueur dans ≤ 2 tickets.
- **Périmètre mince (moins de 15 matchs)** : la fourchette de gains prime sur le nombre de tickets. Faire 2 ou 3 tickets de 6 à 10 jambes
  plutôt que 5 tickets courts à cote 5–25 : un ticket à cote 4 pour 3 € n'est pas ce que Jtab veut jouer (sauf le « discipliné »). Le dire dans `notes`.
- Mix par défaut pour `nb = 5` : 1 « discipliné » (2–3 sélections, cote 3–8, marchés 1N2/double chance/+−2,5/les 2 marquent),
  2 « mélange » (4–8 sélections, ≥ 4 types), 1 « safe » (6–10 sélections ≤ 1,80), 1 « risqué » (3–6 sélections, outsiders/nuls/doublé).
  Cote cible des tickets non disciplinés : `gain_min / mise` à `gain_max / mise`. ≥ 4 sélections à cote ≥ 1,20 déclenchent le Combi Boosté.
- Un nom et une phrase (`story`) par ticket ; `why` d'une ligne par jambe (fait vérifiable : forme, absents, valeur), pas de roman.

Le week-end, le passage de 17h27 suit celui de 12h27 : si `data/tickets.json` du jour contient des tickets dont la `deadline` n'est pas passée,
les garder tels quels (leurs jambes se re-résolvent) et ajouter les nouveaux à la suite ; ne jamais effacer un ticket encore jouable.

## 4. Écrire et vérifier
`data/tickets.json` minimal (le script complète identifiants, cotes, liens, gains, TRJ, deadline) :
```json
{"generated_at": "<ISO UTC>", "params": {"nb": 5, "mise": 3, "gmin": 200, "gmax": 2000},
 "notes": ["…"], "exclusions": [{"match": "…", "player": "…", "reason": "…"}],
 "tickets": [{"name": "…", "style": "melange|safe|risque|discipline", "story": "…", "legs": [
    {"event_id": 1318918, "mk": "1N2", "pick": "2", "why": "…"},
    {"event_id": 1318919, "mk": "OU25", "pick": "Plus"},
    {"event_id": 1318920, "mk": "team_total", "team": "Lille", "line": "1,5", "pick": "Plus"},
    {"event_id": 1318921, "mk": "buteur", "pick": "Panichelli"}]}]}
```
`mk` ∈ `1N2` (pick `1|N|2`), `DC` (`1/N|N/2|1/2`), `OU25` (`Plus|Moins`), `BTTS` (`Oui|Non`), `team_total` (+ `team`, `line` `1,5|2,5`, pick `Plus|Moins`),
`buteur`, `double`, `decisif` (pick = nom tel que dans l'offre ou sous-chaîne unique), `double_match` (`Oui`).
```bash
python3 scripts/check_tickets.py data/tickets.json
```
Code 1 = erreurs listées (bouton introuvable, deux sélections sur un match, couverture, joueur absent, deadline) : corriger la
spécification et relancer jusqu'au code 0. Lire les avertissements et les traiter si c'est un oubli (cote hors fourchette, joueur dans
3 tickets). Ne jamais contourner une erreur en éditant le fichier vérifié à la main.

## 5. Publier
```bash
git add data/tickets.json && git commit -m "tickets $(date -u +%Y-%m-%dT%H:%MZ)" \
  && (git pull --rebase origin main || (git checkout --theirs data/tickets.json; git add data/tickets.json; GIT_EDITOR=true git rebase --continue)) \
  && git push origin HEAD:main
```
Seul `data/tickets.json` est modifié par l'agent. Compte rendu en 10 lignes : périmètre, tickets (nom, cote, gain, deadline), joueurs
écartés et pourquoi, avertissements restants, état des données (âge de l'offre, dispo `status`). Terminer par la ligne honnête :
l'outil organise et évite les erreurs grossières, il ne crée pas d'avantage (espérance négative).
