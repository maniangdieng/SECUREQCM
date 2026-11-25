# Secure QCM 2.0 — Guide rapide

## Installation sur macOS

1. Décompresser `secure_qcm_2.0_complet.zip`.
2. Conserver une copie de l’ancien dossier et de son fichier `db.sqlite3`. Si tu as déjà des comptes, examens ou résultats plus récents, conserve ta base actuelle : ne la remplace pas par celle de l’archive.
3. Ouvrir Terminal dans le dossier `secure_qcm_app`.
4. Exécuter :

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py runserver 0.0.0.0:8000
```

La base `db.sqlite3` fournie dans cette archive contient les comptes et examens présents dans le projet transmis lors de la préparation. Sauvegarder toute base plus récente avant remplacement.

## Accès réseau local

- Étudiant : `http://ADRESSE_IP_DU_MAC:8000/accounts/login/`
- Enseignant : `http://ADRESSE_IP_DU_MAC:8000/dashboard/teacher/`

Le Mac et les appareils étudiants doivent être sur le même réseau et le serveur doit rester démarré.

## Importer un QCM

Depuis l'espace enseignant, cliquer sur **Importer depuis mon ordinateur**.

Formats :
- PDF avec texte sélectionnable (les PDF scannés nécessitent un OCR non inclus).
- Word `.docx`.
- Excel `.xlsx` ou `.xlsm`.

### Format Excel recommandé

Utiliser le fichier `qcm_data/modele_import_qcm.xlsx`. Une ligne par question et les colonnes :

`Question | A | B | C | D | Réponse`

La colonne Réponse accepte `A`, `B`, `C`, `D` ou plusieurs lettres séparées par des virgules, par exemple `A,C`.

### PDF et Word

Présenter chaque question sous la forme :
- `1. Énoncé de la question`
- `A) Proposition A`
- `B) Proposition B`
- `C) Proposition C`
- `D) Proposition D`

Les réponses intégrées peuvent être indiquées sur une ligne `Réponse : B`.

### Trois modes de correction

1. Réponses intégrées au fichier du sujet.
2. Sujet et corrigé séparé (PDF, DOCX ou XLSX avec numéro de question et réponse).
3. Sélection manuelle des bonnes réponses dans l'écran de prévisualisation.

L'import crée toujours un examen **en brouillon**. Vérifier toutes les questions et réponses avant publication.

## Règles d'examen configurées

- Chronomètre global uniquement (durée définie pour l'examen).
- Premier changement d'onglet : avertissement au retour dans l'examen.
- Deuxième changement d'onglet : clôture de la tentative.
- Les réponses sont enregistrées à chaque validation.
- La validation d’une réponse ne doit pas être interprétée comme un changement d’onglet.
- Une tentative clôturée pour sécurité ou interrompue peut être recommencée ; l’ancienne tentative reste conservée dans l’historique.
- Les résultats et copies sont accessibles dans l'espace enseignant.

## Limites à connaître

- Le contrôle de changement d'onglet dépend des événements signalés par le navigateur ; il ne remplace pas un navigateur d'examen sécurisé ni une surveillance.
- Les PDF image/scannés ne sont pas OCRisés.
- Pour Word, utiliser `.docx` et non l'ancien format `.doc`.
- Tester l'import et une tentative complète avec un compte étudiant de test avant un examen réel.

## Affectation automatique par niveau (version 2.6)

- À l'inscription, chaque étudiant renseigne son niveau d'études (L1, L2, L3, M1, M2, Doctorat ou Autre).
- À la création manuelle ou à l'importation d'un QCM, l'enseignant choisit le niveau cible et le mode d'affectation.
- En mode « Tous les étudiants du niveau », la publication affecte automatiquement tous les comptes étudiants de ce niveau. Les nouveaux étudiants inscrits ultérieurement à ce niveau reçoivent également l'examen dans leur tableau de bord.
- En mode « Étudiants sélectionnés », l'enseignant importe un CSV avec une colonne `matricule`. Seuls les étudiants de cette liste voient l'examen.
- Dans les deux modes, l'étudiant doit saisir le code propre à l'examen. Le serveur vérifie également son niveau ou son inscription sur la liste avant d'autoriser le démarrage.
- Les anciens comptes ont un niveau vide après migration : l'administrateur doit renseigner leur niveau dans Django Admin, rubrique Profils. Les anciens examens ont également un niveau vide ; attribuez-leur un niveau avant de les réutiliser.

Migration de cette version : `python manage.py migrate`.


## Connexion unique (version 2.7)

Tous les profils utilisent `/accounts/login/`. Après authentification, Secure QCM redirige automatiquement l'étudiant vers `/dashboard/student/`, l'enseignant vers `/dashboard/teacher/` et le compte staff/superutilisateur vers `/dashboard/admin/`. Le paramètre `next` ne permet pas de contourner cette redirection par rôle. L'inscription étudiant reste accessible via `/accounts/register/`.
