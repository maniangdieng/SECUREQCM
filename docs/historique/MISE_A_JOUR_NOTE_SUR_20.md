# Mise à jour Secure QCM — Note finale sur 20

Cette version complète est basée sur le projet Secure QCM 2.7 fourni et sur le dossier `qcm/` transmis séparément.

## Changements

- Calcul de la note finale sur 20 à partir de la fonction de correction existante `calculate_score`.
- Affichage de la note finale dans la page des résultats de l'enseignant (`templates/qcm/exam_results.html`).
- Ajout de la colonne « Note finale (/20) » dans l'export CSV destiné à Excel.
- Suppression de la définition en doublon de `export_exam_results` dans `qcm/views.py`.
- Les templates étudiants ne sont pas modifiés pour ne pas exposer la note finale côté étudiant.

## Installation

1. Sauvegarder le dossier actuel du projet et la base `db.sqlite3`.
2. Décompresser cette archive.
3. Remplacer l'ancien dossier du projet par le dossier `secure_qcm_app` fourni, ou copier les fichiers en conservant votre base de données et votre fichier `.env`.
4. Activer l'environnement virtuel et installer les dépendances si nécessaire :

   ```bash
   source ~/venv/bin/activate
   pip install -r requirements.txt
   ```

5. Vérifier le projet et lancer les tests :

   ```bash
   python manage.py check
   python manage.py test qcm
   python manage.py runserver 0.0.0.0:8000
   ```

Aucune migration n'est requise pour la note sur 20 : elle est calculée à la demande et n'ajoute aucun champ à la base de données.

## Important

L'export est un CSV séparé par des points-virgules, lisible par Excel. Ce n'est pas un classeur `.xlsx` natif.
