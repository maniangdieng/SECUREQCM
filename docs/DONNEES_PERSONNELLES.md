# Données personnelles

> **À compléter et à faire valider par l'établissement avant toute utilisation avec de vraies personnes.**
> Ce document décrit ce que fait l'application. Il n'est pas un avis juridique.
> Les champs entre `[crochets]` sont à remplir.

## 1. Ce que l'application enregistre

| Données | Contenu | Personnes |
|---|---|---|
| Compte | identifiant, prénom, nom, e-mail (facultatif à l'inscription), mot de passe **haché**, date de création, dernière connexion, rôle | toutes |
| Scolarité | matricule, niveau, classes rejointes et rôle dans la classe | étudiants, enseignants |
| Inscriptions aux examens | examen, origine, code validé, date | étudiants |
| Copies | début, fin, statut, ordre des questions, barème, réponses et leur date, score | étudiants |
| Journal de sécurité | changements d'onglet, sorties du plein écran, pertes de focus, redimensionnements, reprises autorisées (auteur et motif), date | étudiants |
| Journal des opérations | auteur, action, objet concerné, détail, date | administrateurs, enseignants, personnes citées |
| Session | identifiant de connexion ; aperçu temporaire d'un sujet importé | toutes |

Hors de la base : les fichiers **exportés** (résultats), les **sauvegardes** et, après fusion de la PR #31, les
e-mails de réinitialisation confiés au serveur d'e-mail.

L'application dépose deux cookies techniques (`sessionid`, `csrftoken`). Elle n'enregistre pas elle-même d'adresse IP,
n'utilise ni caméra, ni micro, ni outil de mesure d'audience, et ne conserve pas les fichiers de sujets importés.
Le serveur, le proxy ou l'hébergeur peuvent tenir leurs propres journaux : les vérifier.

## 2. Qui voit quoi

| Qui | Accès |
|---|---|
| Étudiant | son compte, ses examens et ses scores ; le nom des enseignants de ses classes et le nombre d'étudiants (pas leurs noms) |
| Enseignant | les membres de ses classes ; les copies, notes et journaux de sécurité de ses examens |
| Administration | tous les comptes, classes, examens, copies et le journal des opérations |
| Personne ayant accès au serveur ou aux sauvegardes | tout |

## 3. Durées de conservation (à fixer par l'établissement)

**L'application ne supprime rien automatiquement**, hormis ce qui est indiqué.

| Données | Durée décidée | Comment supprimer |
|---|---|---|
| Comptes inactifs | `[durée]` | désactiver ; supprimer seulement si le compte n'a ni copie, ni examen, ni classe |
| Copies, réponses, journal de sécurité | `[durée, au moins le délai de réclamation]` | archiver l'examen puis **Supprimer définitivement** |
| Journal des opérations | `[durée]` | aucune fonction dans l'application : intervention sur la base |
| Sessions expirées | `[fréquence]` | `python manage.py clearsessions` à planifier |
| Exports de résultats | `[durée]` | par les personnes qui les ont téléchargés |
| Sauvegardes | `[durée]` | suppression manuelle ou tâche planifiée |
| Journaux du serveur | `[durée]` | réglage du serveur |

Une donnée supprimée subsiste dans les sauvegardes jusqu'à leur propre suppression.

**Limite connue.** Un compte qui a des copies ne peut pas être supprimé, et l'application n'a pas de fonction
d'anonymisation. Une demande d'effacement fondée demande une intervention technique (remplacer identité, e-mail et
matricule), à documenter.

## 4. Mesures de protection en place

Mots de passe hachés (Django) ; contrôle d'accès par rôle et par examen ; jetons CSRF ; en production,
[HTTPS](HTTPS.md) et cookies réservés au HTTPS ; déconnexion après inactivité (8 h par défaut) ; journal des
opérations ; [sauvegardes](SAUVEGARDE.md) lisibles par leur seul auteur.

À la charge de l'établissement : accès au serveur, chiffrement des disques et des copies de sauvegarde, protection des
exports, comptes d'administration nominatifs. Les limites de sécurité de l'application sont décrites dans le
[rapport de validation](RAPPORT_VALIDATION.md).

## 5. Cadre légal au Sénégal (à vérifier)

Texte de référence consulté : **loi n° 2008-12 du 25 janvier 2008** sur la protection des données à caractère
personnel ([texte](https://www.afapdp.org/wp-content/uploads/2018/05/Senegal-texte-de-loi-2008.pdf)). Un projet de
loi de remplacement a été signalé : **vérifier le texte en vigueur** auprès de la
[CDP](https://www.cdp.sn/legislation/textes-legislatifs) (Commission de protection des données personnelles).

Points à examiner avec un juriste :

| Sujet | Articles |
|---|---|
| Déclaration préalable à la CDP, récépissé avant traitement | 18 |
| Autorisation éventuellement requise pour un identifiant national ou général (qualification du **matricule**) | 20 |
| Finalités, pertinence, durée de conservation limitée | 35, 72 |
| Transferts à l'étranger (hébergeur, serveur d'e-mail) | 49 à 51 |
| Information des personnes | 58 |
| Droits d'accès, d'opposition, de rectification et de suppression | 62, 63, 68, 69 |
| Sécurité des données, sauvegardes comprises | 71 |

## 6. Notice à remettre aux étudiants (modèle)

> **Vos données dans Secure QCM**
>
> - **Responsable du traitement** : `[établissement, adresse, contact]`.
> - **Finalités** : organiser des évaluations en ligne, noter, détecter des comportements contraires aux règles de
>   l'examen, traiter les réclamations.
> - **Données** : identité, identifiant, matricule, niveau, e-mail, classes, réponses, notes, journal des événements
>   survenus pendant l'examen (changement d'onglet, sortie du plein écran, perte de focus, redimensionnement).
> - **Destinataires** : vos enseignants, l'administration, `[autres : hébergeur, jury…]`.
> - **Réponses obligatoires** : identité, matricule, niveau et identifiant sont nécessaires pour créer le compte et
>   passer un examen. L'e-mail est facultatif.
> - **Conservation** : `[durées]`.
> - **Transferts à l'étranger** : `[aucun / préciser]`.
> - **Vos droits** : accès, rectification, opposition et suppression dans les conditions prévues par la loi, y compris
>   demander à ne plus figurer dans le fichier. S'adresser à `[contact]`. Vous pouvez saisir la CDP.
>
> Aucune décision disciplinaire ne repose sur le seul journal automatique : vous pouvez donner vos explications.

La dernière phrase engage l'établissement : la garder seulement si cette règle est adoptée.
