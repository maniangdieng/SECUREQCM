# Rapport de validation — 27 novembre 2026

## Version examinée

Branche `main`, commit `d3bbe88` (27/11/2026), qui réunit les évolutions fusionnées jusqu'à la PR #45.

**Conclusion.** Les tests automatiques passent et la surveillance a été essayée à la main dans Chrome sous Linux.
L'application **n'est pas validée pour un examen à fort enjeu** : il reste à essayer les autres navigateurs et les vrais
appareils, à rejouer le déploiement sur cette version, à mesurer la charge sur la machine cible et à faire la
validation juridique.

## 1. Tests automatiques

| Exécution sur `d3bbe88` | Résultat |
|---|---|
| SQLite | 344 tests réussis, dont 3 ignorés (verrous de base, réservés à PostgreSQL) |
| PostgreSQL 16 | 344 tests réussis |
| `check`, migrations manquantes, `ruff` | aucun problème signalé |

Sujets couverts : connexion, blocage après échecs et rôles, mot de passe oublié, profil, classes, publication et
inscriptions, fenêtre d'ouverture, modification et duplication d'examen, passation (chronomètre, sauvegarde
automatique, reprise réseau, accès simultanés), surveillance et reprise autorisée, notation, publication des notes,
résultats, exports, analyse par question, import, administration et journaux.

Relancer : `python manage.py test qcm`. L'intégration continue lance les tests sur SQLite à chaque pull request.

## 2. Essais dans un navigateur

**Essai manuel, 27/11, `d3bbe88`, Google Chrome 158 sous Linux, vrai plein écran, données fictives.**

| Essai | Constaté |
|---|---|
| Alt+Tab | une absence d'au moins 2 secondes compte comme une violation, une perte de focus brève ne compte pas ; la 2e violation clôture l'examen |
| Ouverture d'un nouvel onglet | une seule violation ; la sortie suivante du plein écran clôture l'examen |
| Première violation | avertissement affiché |

La touche Échap avait donné un avertissement puis une clôture le matin même, sur une version antérieure.

**Navigateur automatisé, données fictives, avant les dernières fusions :** passation, annonce de la règle de notation,
clôture et archivage, résultats et page imprimable, pages d'administration, filigrane (dont écran étroit), clic droit,
perte de focus et redimensionnement. Ce navigateur refuse le vrai plein écran.

**Charge :** voir le [test de charge](TEST_DE_CHARGE.md). 200 étudiants simultanés, aucun échec, sur une machine de
développement. La machine cible n'a pas été essayée.

## 3. Déploiement, sur une machine Linux (Docker Compose, PostgreSQL 16, Caddy)

Essais du 27/11 sur la branche `docs/exploitation`, **avant** la fusion d'une partie des évolutions (dont le blocage
des connexions et son réglage derrière Caddy, `AXES_BEHIND_PROXY`). **Ils n'ont pas été rejoués sur `d3bbe88`.**

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
| 1 | Chrome, Firefox, Edge, Safari : plein écran, Alt+Tab, touche Échap (Chrome sous Linux essayé le 27/11, §2 ; les trois autres jamais) | avertissement puis clôture | [ ] |
| 2 | Windows, macOS, Linux | parcours identiques | [ ] |
| 3 | Téléphones et tablettes Android et iOS (le plein écran peut manquer sur iPhone) | décider des appareils admis | [ ] |
| 4 | Notification, appel entrant, mise en veille pendant l'examen | comportement connu et annoncé | [ ] |
| 5 | Coupure Wi-Fi, puis retour ; fermeture et réouverture du navigateur | sélection conservée, reprise | [ ] |
| 6 | Lecteur d'écran et navigation au clavier seul | examen passable | [ ] |
| 7 | Exports dans Microsoft Excel ; impression papier et PDF | accents et colonnes corrects | [ ] |
| 8 | Import de vrais sujets d'enseignants (PDF, Word, Excel, JSON) | questions et corrigés exacts | [ ] |
| 9 | Certificat public sur le nom de domaine final | aucune alerte | [ ] |
| 10 | Certificat interne installé sur les postes des étudiants | aucune alerte | [ ] |
| 11 | Envoi réel d'e-mails (mot de passe oublié) | lien reçu et utilisable | [ ] |
| 12 | Test de charge à l'effectif maximal sur la machine cible ([méthode](TEST_DE_CHARGE.md)) | temps de réponse acceptables, aucune copie perdue | [ ] |
| 13 | Déploiement, sauvegarde et restauration (§3) avec la version finale, sur le serveur de l'établissement | identique à l'origine | [ ] |
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

- La connexion est bloquée 15 minutes après 5 échecs pour un même identifiant depuis une même adresse IP. Les essais
  de codes d'examen et de classe ne sont pas limités.
- Un compte ayant des copies ne peut pas être supprimé ni anonymisé depuis l'application.

**Exploitation**

- Un examen archivé par l'administration pendant des copies en cours disparaît de l'espace étudiant, mais les routes
  de passation ne vérifient pas l'archivage : une page déjà ouverte, ou son adresse directe, accepte encore les
  réponses (constaté par un essai).
- Après la fermeture programmée, un examen jamais commencé reste dans « À faire », marqué « Fermé ». Côté enseignant,
  il reste « Publié » et l'inscription d'un étudiant reste possible.
- Deux cas rares peuvent provoquer une erreur serveur lors d'une reprise : une tentative passée manuellement à
  « interrompue » alors qu'une plus ancienne est encore en cours, ou deux reprises simultanées de deux copies du même
  étudiant.
- N'apparaissent pas au journal des opérations : la création d'un examen (import compris), le changement de durée, de
  notation ou d'ordre, l'ajout, le déplacement et la suppression d'une question, la création et la modification d'une
  classe, les modifications faites dans `/admin/` et la commande `import_qcm`.
- Le conteneur de l'application s'exécute en administrateur (`root`).

## 6. Avant un examen réel

Exécuter le tableau du §4 et la [checklist](DEPLOYMENT_CHECKLIST.md) sur la version qui sera mise en service, après y
avoir relancé les tests.
