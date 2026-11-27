# Sauvegarde et restauration

Cette procédure concerne le déploiement Docker + PostgreSQL. Une sauvegarde contient **des données personnelles**
(noms, matricules, copies, notes) : la protéger comme la base elle-même et **ne jamais la déposer sur Git**.

## Ce qu'il faut conserver

| Élément | Comment |
|---|---|
| La base PostgreSQL (comptes, classes, examens, copies, journaux) | `deploy/sauvegarde.sh` |
| Le fichier `.env` (clé secrète, mots de passe) | copie séparée, dans un coffre à mots de passe ou un support protégé |
| Le code | le dépôt Git |

L'application ne stocke aucun fichier envoyé : les sujets importés sont convertis en questions dans la base.

## Sauvegarder

Depuis le dossier du projet, la pile étant démarrée :

```bash
deploy/sauvegarde.sh                       # écrit dans ~/sauvegardes-secureqcm
deploy/sauvegarde.sh /mnt/disque/sauvegardes
```

Le script affiche le chemin du fichier créé (`secureqcm-AAAAMMJJ-HHMMSS.dump`), lisible par son seul auteur.
Si `pg_dump` échoue, il s'arrête avec une erreur et ne laisse aucun fichier.

Le script suppose Linux ou macOS (bash). Sous Windows, le lancer dans WSL.

### Vérifier un fichier

```bash
docker compose exec -T db pg_restore -f /dev/null < fichier.dump && echo "fichier lisible"
```

Un fichier tronqué provoque une erreur. Ce contrôle ne remplace pas un essai de restauration.

### Planifier

Exemple : chaque soir à 23 h (cron du serveur).

```cron
0 23 * * * /chemin/du/projet/deploy/sauvegarde.sh /mnt/disque/sauvegardes
```

Recommandations, à adapter par l'établissement :

- sauvegarder aussi **juste après chaque examen**, et avant toute mise à jour ;
- garder une copie **hors du serveur**, chiffrée ;
- supprimer les sauvegardes au terme de la durée de conservation fixée (le script ne supprime rien) ;
- faire un essai de restauration au moins une fois par semestre.

## Restaurer

> La restauration **remplace** la base actuelle. Tout ce qui a été saisi depuis la sauvegarde est perdu.
> Sur une installation en service, faire d'abord une nouvelle sauvegarde.

Même procédure sur un serveur vierge (après avoir recopié le code et le fichier `.env`) ou par-dessus une
installation existante :

```bash
docker compose stop web
docker compose up -d --wait db
docker compose exec -T db sh -c 'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose exec -T db sh -c 'pg_restore --no-owner --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < fichier.dump
docker compose up -d
```

Au démarrage, l'application applique les migrations plus récentes que la sauvegarde. Restaurer une sauvegarde
dans une version **plus ancienne** du code n'est pas prévu.

### Contrôler après restauration

1. Se connecter avec un compte administrateur, un compte enseignant et un compte étudiant.
2. Ouvrir les résultats d'un examen terminé et comparer avec un export fait auparavant.
3. En HTTPS avec autorité interne, sur un serveur neuf : réinstaller le certificat sur les postes
   (voir [HTTPS.md](HTTPS.md), §4).

## Essai réalisé

Procédure exécutée sur des **données de démonstration** (PostgreSQL 16, Docker Compose) : sauvegarde, suppression
complète des volumes, restauration, puis restauration par-dessus une installation en service. Dans les deux cas,
les données et les lignes de résultats étaient identiques à l'origine, les trois rôles pouvaient se connecter et une
nouvelle écriture fonctionnait. L'échec de sauvegarde (base arrêtée) et le refus d'un fichier tronqué ont été vérifiés.

À refaire par l'établissement sur son propre serveur avant le premier examen réel.

## Base SQLite (développement)

Application arrêtée, copier `db.sqlite3` suffit. La même précaution s'applique : jamais dans Git.
