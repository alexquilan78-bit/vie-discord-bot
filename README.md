# VIE Watcher → Discord

Un petit robot qui surveille les offres VIE publiées sur
[mon-vie-via.businessfrance.fr](https://mon-vie-via.businessfrance.fr/en/offres/recherche)
(la plateforme officielle de Business France) et t'envoie une notification
Discord dès qu'une offre correspond à tes critères.

Fonctionnement : le script ouvre la page de recherche dans un navigateur headless
(Playwright), repère les offres actuellement affichées, les compare à celles
déjà vues (`seen_offers.json`). Pour chaque offre **nouvelle**, il ouvre sa
page de détail pour en extraire les informations structurées (entreprise,
localisation, durée, indemnité, date de début, référence), vérifie si elle
correspond à `criteria.json`, et si oui l'envoie sur Discord sous forme
d'embed avec ces champs bien mis en forme — dans le même esprit que ceci :

```
🚀 Design Engineer (H/F)
🏢 Entreprise: NEMERA SERVICES     📍 Localisation: CHICAGO -IL- – ETATS-UNIS
🗓️ Durée: 12 mois                  💰 Indemnité: 3 793.61 €
📅 Début: 01/08/2026               📇 Référence: VIE242515
🔗 Lien: Voir l'offre sur Business France
```

Le tout tourne gratuitement toutes les 30 minutes via GitHub Actions.

## ⚠️ À savoir avant de commencer

Le site est une application JavaScript qui ne publie pas d'API publique
documentée. Le script extrait donc les champs (Entreprise, Localisation,
Durée, Indemnité, Début, Référence) en cherchant leurs libellés dans le texte
visible de la page de détail, ce qui est plus robuste qu'un scraping basé sur
des noms de classes CSS (qui changent souvent), mais reste dépendant des
libellés et de la structure actuelle du site. Si un champ n'est pas trouvé, il
s'affichera comme "Non précisé" plutôt que de faire planter le script. Si
Business France change significativement le site, il faudra probablement
ajuster les libellés dans `FIELD_LABELS` (en haut de `vie_watcher.py`) — le
mode `--debug` (voir plus bas) t'aidera à diagnostiquer, en générant le HTML
et une capture d'écran de la page de détail réellement visitée.

## 1. Créer le webhook Discord

1. Dans Discord, va dans le salon où tu veux recevoir les alertes.
2. Paramètres du salon → **Intégrations** → **Webhooks** → **Nouveau webhook**.
3. Donne-lui un nom (ex. "Alertes VIE"), puis clique sur **Copier l'URL du webhook**.
4. Garde cette URL de côté, tu en auras besoin à l'étape 3.

## 2. Créer le dépôt GitHub

1. Crée un nouveau dépôt GitHub (public de préférence — les Actions sont
   gratuites et illimitées sur les dépôts publics ; sur un dépôt privé tu as un
   quota mensuel gratuit qui suffit largement pour un scan toutes les 30 min).
2. Mets-y tous les fichiers de ce projet (`vie_watcher.py`, `criteria.json`,
   `seen_offers.json`, `requirements.txt`, `.github/workflows/vie-watch.yml`).

## 3. Ajouter le secret du webhook

1. Dans le dépôt GitHub : **Settings** → **Secrets and variables** → **Actions**
   → **New repository secret**.
2. Nom : `DISCORD_WEBHOOK_URL`
3. Valeur : colle l'URL copiée à l'étape 1.

## 4. Personnaliser tes critères

Édite `criteria.json` :

```json
{
  "keywords": ["data", "marketing digital"],
  "countries": ["Canada", "Allemagne", "Espagne"],
  "exclude_keywords": []
}
```

- `keywords` : l'offre doit contenir **au moins un** de ces mots (dans le titre,
  le poste, la description...). Laisse `[]` pour ne pas filtrer sur ce critère.
- `countries` : idem, mais pour le pays de la mission.
- `exclude_keywords` : si l'offre contient l'un de ces mots, elle est ignorée
  même si elle matche le reste (utile pour exclure un domaine qui ne t'intéresse pas).

La recherche n'est pas sensible à la casse et fonctionne sur des mots partiels
("informatique" matchera aussi "systèmes d'information" si le mot apparaît
dans le texte visible de l'offre — pense à des mots-clés assez larges).

## 5. Premier lancement : éviter le déluge de notifications

Sans précaution, le tout premier scan enverrait une notification pour **toutes**
les offres actuellement en ligne qui matchent tes critères (potentiellement
des dizaines). Pour l'éviter :

1. Va dans l'onglet **Actions** du dépôt GitHub.
2. Sélectionne le workflow **VIE Watcher**, clique sur **Run workflow**.
3. Mets `seed_only` à `true`, puis lance.

Ce premier run marque toutes les offres actuelles comme "déjà vues" sans rien
envoyer sur Discord. À partir du run suivant (déclenché automatiquement toutes
les 30 minutes, ou manuellement avec `seed_only` à `false`), seules les
**nouvelles** offres correspondant à tes critères seront notifiées.

## 6. C'est parti

À partir de là, le workflow tourne tout seul toutes les 30 minutes. Tu peux
changer la fréquence dans `.github/workflows/vie-watch.yml` (ligne `cron`),
ou modifier `criteria.json` à tout moment (le prochain run prendra en compte
le changement).

## Débogage

Si tu ne reçois aucune notification alors que tu penses qu'il devrait y en
avoir, exécute localement (nécessite Python 3.11+ et `pip install -r
requirements.txt && playwright install chromium`) :

```bash
export DISCORD_WEBHOOK_URL="ton_url_de_webhook"
python vie_watcher.py --debug
```

Cela génère `debug_listing.html` / `debug_listing.png` (page de recherche) et,
pour chaque nouvelle offre traitée, `debug_offer_<id>.html` / `.png` (page de
détail) — utile pour vérifier que les libellés (Entreprise, Localisation...)
sont bien repérés et ajuster `FIELD_LABELS` si besoin.
