# Secure QCM 2.1 — version inspectée et mise à jour

## Modifications de cette livraison

### Suppression pendant la prévisualisation de l'importation
- Chaque question importée possède une case « Supprimer cette question ».
- Les questions cochées sont retirées avant la création de l'examen.
- Les réponses correctes sont vérifiées uniquement pour les questions conservées.
- Il faut conserver au moins une question.
- Les questions restantes sont renumérotées automatiquement dans l'examen créé.

### Suppression après l'importation
- La page de gestion de l'examen en brouillon conserve le bouton de suppression individuelle déjà présent.
- La suppression reste interdite après publication ou lorsqu'une tentative est déjà associée à l'examen, afin de préserver l'historique des résultats.

### Temps par question
- Le temps de chaque question est réparti en secondes entières à partir de la durée totale divisée par le nombre de questions.
- Les secondes restantes sont attribuées une par une aux premières questions.
- La somme des temps par question correspond exactement à la durée totale.
- Le chronomètre global reste la limite absolue.
- À l'expiration du temps d'une question, la réponse est enregistrée automatiquement comme blanche si aucune réponse n'a été soumise, puis l'examen passe à la suivante.

Exemple : 60 minutes pour 7 questions donnent 515, 515, 515, 515, 514, 514 et 514 secondes, soit exactement 3 600 secondes.

## Installation

1. Faire une copie de sauvegarde du dossier et de `db.sqlite3`.
2. Décompresser cette archive complète.
3. Remplacer les fichiers du projet par ceux de cette archive, mais conserver la base de données actuelle si elle contient des comptes, examens ou résultats récents.
4. Dans le dossier du projet :

```bash
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 0.0.0.0:8000
```

Aucune modification du schéma de base de données n'est nécessaire pour ces fonctionnalités.

## Vérifications effectuées lors de la préparation
- Vérification de la structure de l'archive source.
- Compilation syntaxique des fichiers Python modifiés.
- Vérification de l'intégrité de l'archive ZIP finale.
- Ajout d'un test unitaire pour vérifier que la répartition entière totalise exactement la durée globale.

Les tests Django doivent être exécutés dans l'environnement de l'application. Ne pas considérer cette livraison comme validée pour un examen officiel avant un essai complet avec un compte enseignant et un compte étudiant.
\n\n## Version 2.2 — Gestion des examens\n- Ajout d'un bouton de suppression d'examen avec confirmation. Suppression autorisée uniquement sans tentative; questions et options sont supprimées en cascade.\n- Ajout d'un formulaire de modification de durée, autorisé uniquement avant toute tentative.\n\n\n## Version 2.3 — Export CSV des résultats\n- Le CSV expose explicitement le score obtenu, le score maximal, le pourcentage calculé sur toutes les questions et la nature provisoire/définitive du score.\n\n\n## Version 2.4 — Conservation du score après violation\n- À la clôture pour violation, le score des réponses déjà enregistrées est conservé et affiché avec le maximum et le pourcentage.\n- L'export CSV marque le score comme définitif et indique le motif de clôture.\n

## Version 2.7 — Connexion unique et redirection par rôle
- Une page de connexion commune est utilisée par les étudiants, les enseignants et les administrateurs : `/accounts/login/`.
- Après authentification, redirection directe vers le tableau de bord correspondant au rôle du compte.
- Le paramètre `next` ne peut pas rediriger un utilisateur vers l'espace d'un autre rôle.
- Un utilisateur déjà connecté qui ouvre la page de connexion est redirigé vers son tableau de bord.
- La page de connexion propose un lien vers l'inscription étudiant.
