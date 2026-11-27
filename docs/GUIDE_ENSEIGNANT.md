# Guide de l'enseignant

Le compte enseignant est créé, ou le rôle attribué, par l'administration.

## Les classes

- **+ Créer une classe** : nom, section, matière, niveau, couleur. Un **code de classe** (7 caractères) est généré.
- Onglet **Personnes** : **Ajouter par matricules** des étudiants qui ont déjà un compte ; **Retirer** un membre
  (ses résultats sont conservés) ; **Inviter un co-enseignant** par identifiant ou e-mail (propriétaire seulement).
- Onglet **Paramètres** : autoriser ou fermer l'inscription par code, **Générer un nouveau code** (l'ancien cesse de
  fonctionner), **Archiver / Restaurer la classe** (propriétaire). Une classe ne peut être supprimée que si elle ne
  contient aucun examen.

## Créer un examen

Depuis une classe, onglet **Travaux & examens → Nouvel examen**, ou, sans classe,
**Créer un examen par niveau (sans classe)**.

| Réglage | Choix |
|---|---|
| Destinataires | toute la classe, un niveau, ou une liste d'étudiants (CSV) |
| Durée | 1 à 180 minutes, répartie à parts égales entre les questions |
| Choix multiples | **Points partiels** (par défaut) ou **Tout ou rien** |
| Ordre des questions / des réponses | aléatoire ou fixe |

La durée, la notation et l'ordre ne sont **plus modifiables dès qu'un étudiant a commencé**.

L'examen est créé en **brouillon**.

### La règle de notation

- Choix unique : tous les points pour la bonne réponse, zéro sinon.
- Choix multiples, **points partiels** : (bonnes réponses cochées − mauvaises cochées) ÷ nombre de bonnes réponses,
  ramené entre 0 et 1, puis multiplié par les points de la question.
- Choix multiples, **tout ou rien** : les points seulement si la sélection est exactement juste.
- Une question sans réponse vaut zéro. La note finale est ramenée sur 20 ; la réussite est à 10/20.

La règle choisie est affichée aux étudiants avant le démarrage et sur chaque question à choix multiples.

### Saisir les questions

**Ajouter une question** : énoncé, réponse unique ou multiple, points (0,1 à 100), 2 à 8 propositions, au moins une
bonne réponse.

### Importer un sujet

**Importer un QCM** accepte les fichiers PDF, Word (DOCX) et Excel (XLSX, XLSM), 15 Mo au plus.

1. Choisir le fichier, la classe, les destinataires et la source des bonnes réponses : intégrées au sujet, corrigé
   séparé, ou saisie manuelle.
2. **Analyser et prévisualiser** : relire chaque question, corriger, **Retirer** les questions mal lues.
3. **Créer l'examen en brouillon**.

Formats reconnus :

- PDF et Word : une proposition par ligne (`A)`, `B)`, …), avec éventuellement `Réponse : B`.
- Excel : colonnes **Question**, **A** à **D**, **Réponse**. Un modèle se trouve dans
  [`qcm_data/modele_import_qcm.xlsx`](../qcm_data/modele_import_qcm.xlsx).
- Un PDF **scanné** (image) n'est pas lu.

Après fusion de la PR #36 : colonnes Excel jusqu'à **H**, et import **JSON** :

```json
{"questions": [
  {"text": "2 + 2 = ?", "type": "SINGLE", "points": 1,
   "options": [{"text": "4", "correct": true}, {"text": "5", "correct": false}]}
]}
```

`type` et `points` sont facultatifs. Fichier en UTF-8, 500 questions au plus, propositions A à H. Si une question est
invalide, rien n'est importé.

Toujours relire la prévisualisation : c'est le seul contrôle des bonnes réponses avant publication.

## Publier et communiquer le code

**Publier l'examen** rend les questions **définitives**. La page affiche alors le **code d'accès de l'examen**, que les
étudiants saisissent pour y accéder. Il est différent du code de classe.

- **Inscrire un étudiant** par son matricule : utile pour un retardataire ou un étudiant hors du public visé.
- **Liste d'étudiants (CSV)** : une colonne `matricule`. Elle fait passer l'examen en mode « liste » ; si l'examen
  visait une classe ou un niveau, **seuls les étudiants du fichier restent inscrits**.

## Pendant l'examen

- Le chronomètre est géré par le serveur : il continue si l'étudiant ferme la page.
- Pas de retour en arrière. À la fin du temps d'une question, la sélection enregistrée est conservée et l'examen
  avance.
- Quitter le plein écran, changer d'onglet ou quitter la fenêtre plus de 2 secondes (Alt+Tab) est une violation :
  avertissement à la première, clôture à la seconde.
  Recharger la page compte comme une violation ; la fermer peut aussi en enregistrer une.
- **Clôturer** empêche tout nouveau démarrage ; les copies en cours se terminent dans leur temps.

### Autoriser une reprise

Sur la copie d'un étudiant clôturée pour sécurité : **Autoriser une reprise** et indiquer le motif. L'étudiant
revient à la même question, ses réponses sont conservées, le temps qui restait lui est rendu et le compteur de
violations repart à zéro. Impossible si le temps était déjà écoulé ou si l'examen est archivé.

## Les résultats

La page des résultats donne les statistiques, la liste des copies (**Copie** pour le détail) et l'**analyse par
question** : taux de réussite, non-réponses, propositions choisies ; les questions réussies à plus de 90 % ou à moins
de 20 % sont signalées.

- **Exporter en Excel**, **Exporter en CSV**, **Imprimer / PDF**.
- La copie d'un étudiant montre le **journal de sécurité** : *Violation*, *Ignoré* (doublon à moins de 3 secondes),
  *Information* (perte de focus, redimensionnement), *Reprise autorisée*.

Le journal est un **indice**, pas une preuve : un navigateur ordinaire ne verrouille pas le poste, et un événement
peut avoir une cause innocente (notification, appel, panne). Entendre l'étudiant avant toute décision.

Les fichiers exportés contiennent des données personnelles : les garder sur un support protégé.

## Fin de vie d'un examen

Sans tentative, **Supprimer l'examen**. Avec des tentatives, **Archiver l'examen** (une fois les copies en cours
terminées). La suppression définitive est réservée à l'administration.

## Après fusion de la PR #38

La PR #38 ajoute une fenêtre d'ouverture, la modification de questions, la duplication d'examen et la publication des
notes. Ce guide sera à compléter à ce moment-là.
