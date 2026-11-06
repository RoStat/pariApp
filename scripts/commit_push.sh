#!/usr/bin/env bash
# Commit + push des fichiers générés (data/, journal/) sur la pointe de la branche, sans rebase.
# Les fichiers de data/ sont régénérés entièrement à chaque passage : en cas de course avec un autre run, le plus récent gagne.
# Usage : scripts/commit_push.sh [préfixe du message]   (variables : GITHUB_REF_NAME ou branche courante ; DRY_RUN=1 pour ne rien pousser)
set -u
PREFIX="${1:-relais}"
BR="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
git config user.name "pariapp-relais" >/dev/null
git config user.email "bot@users.noreply.github.com" >/dev/null
for i in 1 2 3 4; do
  git fetch --quiet origin "$BR" || { echo "fetch échoué"; sleep $((i*5)); continue; }
  git reset --quiet --soft "origin/$BR"
  git add data journal
  if git diff --cached --quiet; then echo "rien de nouveau"; exit 0; fi
  git commit --quiet -m "$PREFIX $(date -u +%Y-%m-%dT%H:%MZ)"
  if [ "${DRY_RUN:-0}" = "1" ]; then echo "DRY_RUN : commit local $(git rev-parse --short HEAD), pas de push"; exit 0; fi
  git push --quiet origin "HEAD:$BR" && { echo "poussé $(git rev-parse --short HEAD) sur $BR"; exit 0; }
  echo "push refusé (autre run passé avant), nouvel essai dans $((i*5)) s"; sleep $((i*5))
done
echo "push abandonné après 4 essais"; exit 1
