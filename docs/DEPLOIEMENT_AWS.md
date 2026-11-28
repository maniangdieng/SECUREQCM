# Déploiement sur AWS

Un serveur EC2 fait tourner le `docker compose` du projet (PostgreSQL, application, Caddy pour le HTTPS).
Chaque push sur `main` est mis en service automatiquement, une fois la CI réussie.

```
push sur main ─► CI (lint, tests) ─► « Déploiement AWS » (GitHub Actions)
                                        │ OIDC : rôle secureqcm-github-deploy, sans clé stockée
                                        ▼
                         AWS Systems Manager ─► serveur EC2 : git checkout <commit>
                                                             deploy/aws/deploy.sh
```

| Élément | Choix |
|---|---|
| Région | `eu-north-1` (Stockholm) |
| Serveur | `c7i-flex.large` (2 vCPU, 4 Go, inclus dans l'offre gratuite AWS ; `t3.medium` ailleurs), Ubuntu 24.04, disque chiffré de 30 Go, IP fixe |
| Adresse | `https://<ip-avec-tirets>.sslip.io` (certificat Let's Encrypt obtenu par Caddy) |
| Ports ouverts | 80 et 443 seulement. **Pas de SSH** : l'accès passe par Session Manager |
| Secrets | générés sur le serveur dans `/opt/secureqcm/.env` (lisible par root seul), jamais dans Git ni GitHub |
| Tâches planifiées | clôture des tentatives expirées chaque minute ; sauvegarde chaque nuit dans `/var/backups/secureqcm` (14 jours) |

## Installation (une seule fois)

1. Console AWS, région `eu-north-1`, ouvrir **CloudShell** et lancer :
   ```bash
   curl -fsSL https://raw.githubusercontent.com/maniangdieng/SECUREQCM/main/deploy/aws/infra.sh -o infra.sh
   bash infra.sh
   ```
   Le script affiche l'adresse du site et trois valeurs. L'installation du serveur prend 5 à 10 minutes
   (journal : `/var/log/secureqcm-setup.log`).
2. GitHub, **Settings → Secrets and variables → Actions → Variables** : créer `AWS_REGION`, `AWS_INSTANCE_ID` et
   `AWS_DEPLOY_ROLE_ARN` avec les valeurs affichées.
3. Créer le premier administrateur : console EC2 → instance `secureqcm` → **Se connecter → Session Manager**, puis
   ```bash
   cd /opt/secureqcm && sudo docker compose exec web python manage.py createsuperuser
   ```

## Au quotidien

- **Déployer** : fusionner dans `main`. Suivi dans l'onglet **Actions → Déploiement AWS**. Relancer à la main :
  **Run workflow** sur ce même workflow. Seul le commit en tête de `main` est mis en service automatiquement.
- **Pendant un examen** : créer la variable du dépôt `DEPLOY_PAUSE=1` (**Settings → Secrets and variables → Actions →
  Variables**) pour suspendre les déploiements automatiques, la remettre à `0` après. Les fusions faites pendant la
  pause ne sont mises en ligne qu'à la fusion suivante : lancer **Run workflow** pour les déployer tout de suite.
- **Ce que fait un déploiement** : construction de l'image (le site tourne encore), sauvegarde de la base, migrations
  dans un conteneur à part (en cas d'échec, l'ancienne version reste en ligne), puis bascule du conteneur web
  (quelques secondes d'indisponibilité) et rechargement de Caddy.
- **Migration en échec** : le site reste sur l'ancienne version ; le détail est dans
  `/var/log/secureqcm-migration.log` sur le serveur (jamais dans les journaux GitHub, publics). Les migrations passées
  avant celle qui a échoué restent appliquées : si l'une retire une colonne encore utilisée par l'ancienne version,
  restaurer la sauvegarde faite juste avant (voir [SAUVEGARDE.md](SAUVEGARDE.md)).
- **Erreurs des tâches planifiées** : `journalctl -t secureqcm-cloture -t secureqcm-sauvegarde`.
- **Journaux** : Session Manager, puis `cd /opt/secureqcm && sudo docker compose logs --tail 100 web`.
- **Revenir à une version** : relancer le workflow d'un commit précédent, ou sur le serveur
  `sudo git checkout <commit> && sudo bash deploy/aws/deploy.sh`. Les migrations ne sont pas annulées.
- **Récupérer une sauvegarde** : voir [SAUVEGARDE.md](SAUVEGARDE.md). Les sauvegardes restent sur le même disque :
  les copier ailleurs (S3, autre machine) avant un vrai examen.

## À faire avant un vrai examen

- **Données personnelles** : le serveur est en Suède (Stockholm). Examiner le transfert hors du Sénégal (loi 2008-12,
  articles 49 à 51) et compléter la notice aux étudiants (`[aucun / préciser]`) dans
  [DONNEES_PERSONNELLES.md](DONNEES_PERSONNELLES.md) avant d'y mettre de vraies données. Le site est public :
  l'inscription est ouverte à tous.

- E-mails : la configuration écrit les messages dans les journaux (`console`). Pour « Mot de passe oublié »,
  renseigner un serveur SMTP dans `/opt/secureqcm/.env` puis `sudo bash deploy/aws/deploy.sh`.
- Allonger le HSTS dans `deploy/Caddyfile` une fois l'adresse définitive (voir [HTTPS.md](HTTPS.md)).
- Faire le test de charge sur ce serveur ([TEST_DE_CHARGE.md](TEST_DE_CHARGE.md)) et la
  [checklist de déploiement](DEPLOYMENT_CHECKLIST.md).

## Coût et arrêt

Avec l'offre gratuite AWS, le serveur et 30 Go de disque sont couverts dans ses limites ; sinon environ 35 $/mois. L'IP fixe est facturée (environ 3,6 $/mois).
**Le plan gratuit s'arrête au bout de 6 mois ou à l'épuisement des crédits** (100 à 200 $, soit environ 2 à 5 mois à
ce rythme) : passer le compte en payant avant cette date, sinon le serveur, et la base qu'il contient, sont arrêtés. Pour tout supprimer : terminer l'instance
`secureqcm`, libérer l'IP élastique `secureqcm`, supprimer le groupe de sécurité `secureqcm-web` et les rôles IAM
`secureqcm-ec2` et `secureqcm-github-deploy`. **Terminer l'instance efface la base** : sauvegarder avant.
