# Rapport de validation — 27 novembre 2026

## Version examinée

Branche `docs/exploitation`, qui contient `main` et les PR #22, #32, #33, #34, #35, #37, #39 et #40.
Ces PR **ne sont pas encore relues ni fusionnées** : ce rapport ne vaut pas pour `main` seul.

**Conclusion.** Les parcours principaux sont couverts par des tests automatiques et le déploiement HTTPS avec
sauvegarde a été essayé sur une machine. L'application **n'est pas validée pour un examen à fort enjeu** : les essais
sur de vrais appareils, le test de charge et la validation juridique restent à faire.

## 1. Tests automatiques

| Exécution | Résultat |
|---|---|
| SQLite | 216 tests réussis, dont 3 ignorés (verrous de base, réservés à PostgreSQL) |
| PostgreSQL 16 | 216 tests réussis |
| Fusion d'essai avec les PR #30, #31 et #36 (SQLite et PostgreSQL 16) | 249 tests réussis, aucune migration manquante |

Sujets couverts : connexion et rôles, classes, publication et inscriptions, passation (chronomètre, sauvegarde
automatique, reprise réseau, accès simultanés), surveillance et reprise autorisée, notation, résultats, exports,
analyse par question, administration et journaux, protections d'import et d'export.

Relancer : `python manage.py test qcm`. Les PR #18 à #21 et #38 n'ont pas été fusionnées avec cette branche :
**leur compatibilité d'ensemble n'est pas validée** (conflits constatés avec #38, #19 et, entre elles, #36 et #18).

## 2. Essais dans un navigateur

Navigateur automatisé, données fictives : passation, annonce de la règle de notation, clôture et archivage, résultats
et page imprimable, pages d'administration, filigrane (dont écran étroit), clic droit, perte de focus et
redimensionnement.

Limite importante : ce navigateur **refuse le vrai plein écran**. La surveillance reste à essayer sur de vrais postes.

## 3. Déploiement, sur une machine Linux (Docker Compose, PostgreSQL 16, Caddy)

| Essai | Résultat |
|---|---|
| Parcours complet en HTTPS par `localhost` et par `127.0.0.1`, certificat vérifié (publication, deux étudiants, clôture de sécurité, exports, journal, `/admin/`) | réussi |
| Certificat refusé tant que l'autorité interne n'est pas connue | conforme |
| Redirection HTTP → HTTPS, HSTS, cookies `Secure`, origine étrangère refusée | réussi |
| Port 8000 injoignable | réussi |
| `check --deploy` | seuls W004 et W008, assurés par Caddy |
| Accès par adresse IP du réseau et par nom en `.local` (Caddy seul, sans l'application) | certificat vérifié |
| Certificat interne conservé après recréation de Caddy | réussi |
| Sauvegarde, effacement des volumes, restauration | données et résultats identiques, connexion des trois rôles, nouvelle écriture |
| Restauration par-dessus une installation en service | données identiques |
| Sauvegarde avec base arrêtée ; fichier tronqué | erreur signalée, aucun fichier partiel ; fichier refusé |

## 4. Reste à essayer

Cocher et dater au fur et à mesure.

| # | Essai | Attendu | Fait |
|---|---|---|---|
| 1 | Chrome, Firefox, Edge, Safari : plein écran, Alt+Tab, touche Échap | avertissement puis clôture | [ ] |
| 2 | Windows, macOS, Linux | parcours identiques | [ ] |
| 3 | Téléphones et tablettes Android et iOS (le plein écran peut manquer sur iPhone) | décider des appareils admis | [ ] |
| 4 | Notification, appel entrant, mise en veille pendant l'examen | comportement connu et annoncé | [ ] |
| 5 | Coupure Wi-Fi, puis retour ; fermeture et réouverture du navigateur | sélection conservée, reprise | [ ] |
| 6 | Lecteur d'écran et navigation au clavier seul | examen passable | [ ] |
| 7 | Exports dans Microsoft Excel ; impression papier et PDF | accents et colonnes corrects | [ ] |
| 8 | Import de vrais sujets d'enseignants (PDF, Word, Excel) | questions et corrigés exacts | [ ] |
| 9 | Certificat public sur le nom de domaine final | aucune alerte | [ ] |
| 10 | Certificat interne installé sur les postes des étudiants | aucune alerte | [ ] |
| 11 | Envoi réel d'e-mails (PR #31) | lien reçu et utilisable | [ ] |
| 12 | Test de charge à l'effectif maximal (issue #8, PR #21) | temps de réponse acceptables, aucune copie perdue | [ ] |
| 13 | Restauration sur le serveur de l'établissement | identique à l'origine | [ ] |
| 14 | Examen blanc avec une classe volontaire | incidents recensés | [ ] |
| 15 | Validation juridique ([données personnelles](DONNEES_PERSONNELLES.md)) | déclaration et notice | [ ] |

## 5. Limites et points connus

**Surveillance**

- Elle repose sur le navigateur : contournable (second appareil, outils du navigateur), avec des faux positifs.
  Elle ne remplace ni un surveillant ni Safe Exam Browser, qui n'est pas intégré.
- Recharger la page d'examen enregistre une violation.
- Une perte de focus de plus de 2 secondes est une violation, quelle qu'en soit la cause (Alt+Tab, fenêtre système,
  appel). Des allers-retours plus courts ne comptent pas.
- Une seconde violation réelle survenant moins de 3 secondes après la première est ignorée comme doublon.
- Les consignes annoncent une clôture « définitive » alors qu'une reprise peut être autorisée.

**Comptes et accès**

- Pas de limitation des essais de mot de passe ni de codes (la PR #19 traite les essais de connexion).
- Un compte ayant des copies ne peut pas être supprimé ni anonymisé depuis l'application.

**Exploitation**

- Un examen archivé par l'administration pendant des copies en cours disparaît de l'espace étudiant, mais les routes
  de passation ne vérifient pas l'archivage : une page déjà ouverte, ou son adresse directe, accepte encore les
  réponses (constaté par un essai).
- Deux cas rares peuvent provoquer une erreur serveur lors d'une reprise : une tentative passée manuellement à
  « interrompue » alors qu'une plus ancienne est encore en cours, ou deux reprises simultanées de deux copies du même
  étudiant.
- Les modifications faites dans `/admin/` et la commande `import_qcm` n'apparaissent pas au journal des opérations.
- Le conteneur de l'application s'exécute en administrateur (`root`) et Gunicorn démarre avec un seul processus par
  défaut.

## 6. Avant un examen réel

Fusionner les PR après relecture, relancer les tests sur le résultat, exécuter le tableau du §4 et la
[checklist](DEPLOYMENT_CHECKLIST.md).
