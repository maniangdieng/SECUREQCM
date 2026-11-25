# Secure QCM 2.2 — Gestion des examens

## Nouvelles fonctionnalités

### Supprimer un examen
Dans l'espace enseignant, chaque examen possède un bouton **Supprimer l'examen**.
- Une confirmation navigateur est demandée avant l'envoi.
- La suppression est réalisée uniquement par une requête POST protégée par CSRF.
- Si aucune tentative n'existe, l'examen est supprimé et les questions/propositions associées sont supprimées en cascade.
- Si au moins une tentative existe (en cours, terminée, interrompue ou clôturée), la suppression est bloquée pour préserver l'historique et les résultats.

### Modifier la durée
Chaque examen possède un champ de durée et un bouton **Modifier la durée** dans la liste des examens.
- Valeur entière comprise entre 1 et 180 minutes.
- Modification autorisée uniquement si aucune tentative n'existe.
- La modification est bloquée dès qu'un étudiant a commencé l'examen, afin de ne pas perturber une session ou modifier les conditions d'une évaluation déjà engagée.

## Installation sur macOS

1. Sauvegarder le dossier du projet et surtout `db.sqlite3`.
2. Décompresser cette archive complète.
3. Copier les fichiers de cette version dans le dossier du projet existant. Conserver la base de données actuelle si elle contient les comptes, examens et résultats à garder.
4. Depuis le dossier contenant `manage.py` :

```bash
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 0.0.0.0:8000
```

Aucune nouvelle migration de base de données n'est requise pour ces deux fonctionnalités.

## Accès
Espace enseignant : `http://192.168.1.12:8000/dashboard/teacher/`

L'adresse IP peut changer selon le réseau Wi-Fi. Si les appareils ne peuvent pas joindre le serveur, vérifier l'adresse locale du Mac et `ALLOWED_HOSTS`.


## Export CSV des résultats — score définitif et pourcentage

Le fichier CSV téléchargé depuis les résultats comporte les colonnes :
- **Score obtenu** : somme des points obtenus sur les questions de l'examen.
- **Score maximal** : somme des points de toutes les questions de l'examen.
- **Pourcentage (%)** : `Score obtenu / Score maximal × 100`.
- **Nature du score** : `Définitif` lorsque la tentative est terminée, ou `Provisoire` lorsqu'elle est encore en cours.

Les questions sans réponse valent zéro point. Le score maximal prend toujours en compte toutes les questions, même celles laissées blanches. Le pourcentage est arrondi à une décimale dans le CSV.


## Conservation du score en cas de violation

Lorsqu'une tentative est clôturée pour violation des règles (deuxième changement d'onglet), le système conserve les réponses déjà enregistrées. La page de clôture affiche le score obtenu, le score maximal et le pourcentage calculé sur toutes les questions. Dans l'export CSV, la tentative apparaît comme un score définitif, avec le motif « Violation des règles ».

Important : seules les réponses déjà soumises/enregistrées avant la clôture sont comptabilisées. Une sélection encore affichée à l'écran mais non validée au moment de la violation n'est pas considérée comme une réponse enregistrée.
