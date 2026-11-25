# Mise à jour – blocage définitif après deux violations

Cette mise à jour ajoute un verrouillage définitif de l'accès à un examen pour un étudiant dont une tentative est au statut `TERMINATED_SECURITY`.

- La première violation est enregistrée et déclenche l'avertissement existant.
- La deuxième violation clôture la tentative avec le statut `TERMINATED_SECURITY`.
- L'étudiant ne peut plus créer une nouvelle tentative pour cet examen, même après déconnexion/reconnexion.
- L'accès direct à l'ancienne URL de la tentative clôturée redirige vers le tableau de bord étudiant.
- Les réponses déjà enregistrées restent dans la base et le score reste calculable pour le suivi enseignant.

## Installation sur le Mac

1. Arrêter le serveur avec `Ctrl+C`.
2. Faire une copie de la base actuelle :
   `cp ~/Documents/secure_qcm_app/db.sqlite3 ~/Desktop/db_secure_qcm_avant_blocage.sqlite3`
3. Décompresser cette mise à jour dans un nouveau dossier temporaire.
4. Copier les fichiers `qcm/views.py` et `qcm/tests.py` dans le projet actuel, en conservant les autres fichiers et surtout la base `db.sqlite3` actuelle.
5. Depuis le dossier du projet :
   `source ~/venv/bin/activate`
   `python manage.py check`
   `python manage.py test qcm`
6. Redémarrer :
   `python manage.py runserver 0.0.0.0:8000`

Aucune nouvelle migration n'est nécessaire : la mise à jour utilise le statut `TERMINATED_SECURITY` déjà présent dans le modèle `Attempt`.

Important : cette archive ne contient volontairement pas de base `db.sqlite3`, afin d'éviter de remplacer les comptes, examens et résultats du projet installé.
