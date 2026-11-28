# Guide de l'enseignant

Le compte enseignant est créé, ou le rôle attribué, par l'administration.

## Les classes

- **Créer une classe** (bouton **+**) : nom, section, matière, niveau, couleur. Un **code de classe** (7 caractères)
  est généré.
- Onglet **Personnes** :
  - **Ajouter des étudiants** (icône), puis le champ « Ou ajoutez-les par matricule » : un matricule par ligne, ou
    séparés par des virgules. Les étudiants doivent déjà avoir un compte.
  - **Retirer** un membre (ses résultats sont conservés).
  - **Inviter un co-enseignant** (icône, propriétaire seulement) par identifiant ou e-mail.
- Onglet **Notes** : tableau des notes par étudiant et par examen (dernière tentative). Pas d'export depuis ce tableau.
- **Paramètres de la classe** (icône) : autoriser ou fermer l'inscription par code, **Réinitialiser** le code (l'ancien
  cesse de fonctionner), **Archiver / Restaurer** la classe (propriétaire). Une classe ne peut être supprimée que si
  elle ne contient aucun examen.

## Créer un examen

Depuis une classe, onglet **Travaux et devoirs → Créer → Examen QCM** (ou **Importer un sujet**). Sans classe, depuis
l'accueil : **Examens hors classe → Créer un examen par niveau (sans classe)**.

| Réglage | Choix |
|---|---|
| Destinataires | toute la classe ou une liste d'étudiants (CSV) ; hors classe, un niveau ou une liste |
| Durée | 1 à 180 minutes, répartie à parts égales entre les questions |
| Choix multiples | **Points partiels** (par défaut) ou **Tout ou rien** |
| Ordre des questions / des réponses | aléatoire ou fixe |
| Ouverture / Fermeture | facultatives |
| Montrer la note dès la remise de la copie | case décochée par défaut |

La durée, la notation et l'ordre ne sont **plus modifiables dès qu'un étudiant a commencé**.

L'examen est créé en **brouillon**.

### La règle de notation

- Choix unique : tous les points pour la bonne réponse, zéro sinon.
- Choix multiples, **points partiels** : (bonnes réponses cochées − mauvaises cochées) ÷ nombre de bonnes réponses,
  ramené entre 0 et 1, puis multiplié par les points de la question.
- Choix multiples, **tout ou rien** : les points seulement si la sélection est exactement juste.
- Une question sans réponse vaut zéro. La note finale est ramenée sur 20 ; la réussite est à 10/20.

La règle choisie est affichée aux étudiants avant le démarrage et sur chaque question à choix multiples.

### Saisir et corriger les questions

**Ajouter une question** : énoncé, réponse unique ou multiple, points (0,1 à 100), 2 à 8 propositions, au moins une
bonne réponse.

Tant que l'examen est en brouillon et sans tentative, chaque question peut être modifiée (**Modifier**), déplacée
(**↑**, **↓**) ou supprimée.

### Importer un sujet

**Importer un QCM** accepte les fichiers PDF, Word (DOCX), Excel (XLSX, XLSM) et JSON, 15 Mo au plus.

1. Choisir le fichier, la classe, les destinataires et la source des bonnes réponses : intégrées au sujet, corrigé
   séparé, ou saisie manuelle.
2. **Analyser et prévisualiser** : relire chaque question, corriger, **Retirer** les questions mal lues.
3. **Créer l'examen en brouillon**.

Formats reconnus :

- PDF et Word : une proposition par ligne (`A)`, `B)`, …), avec éventuellement `Réponse : B`.
- Excel : colonnes **Question**, **A** à **D** (jusqu'à **H**), **Réponse**. Un modèle se trouve dans
  [`qcm_data/modele_import_qcm.xlsx`](../qcm_data/modele_import_qcm.xlsx).
- Un PDF **scanné** (image) n'est pas lu.
- JSON :

```json
{"questions": [
  {"text": "2 + 2 = ?", "type": "SINGLE", "points": 1,
   "options": [{"text": "4", "correct": true}, {"text": "5", "correct": false}]}
]}
```

`type` et `points` sont facultatifs. Fichier en UTF-8, 500 questions au plus, propositions A à H. Si une question du
fichier JSON est invalide, rien n'est importé.

Toujours relire la prévisualisation avant de publier : elle sert à vérifier les bonnes réponses.

### Dupliquer un examen

Sur la page de l'examen, carte **Dupliquer** : choisir la **classe cible** puis **Dupliquer en brouillon**. La copie
reprend les questions et les réglages, avec un nouveau code d'accès, sans tentative, inscription ni fenêtre
d'ouverture.

## Publier et communiquer le code

**Publier l'examen** rend les questions **définitives**. Les étudiants saisissent le **code d'accès de l'examen**,
affiché sur sa page. Il est différent du code de classe et ne fonctionne qu'une fois l'examen publié.

- **Inscrire** un étudiant par son matricule : utile pour un retardataire ou un étudiant hors du public visé.
- **Liste d'étudiants (CSV)** : une colonne `matricule`. Elle fait passer l'examen en mode « liste » ; si l'examen
  visait une classe ou un niveau, **seuls les étudiants du fichier restent inscrits**.

### Fenêtre d'ouverture

Carte **Fenêtre d'ouverture** : **Ouverture** et **Fermeture** ; un champ vide ne fixe pas de limite. Avant
l'ouverture, l'étudiant peut valider son code mais pas commencer. Après la fermeture, plus personne ne peut commencer ;
une tentative commencée avant la fermeture va au bout de sa durée.

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

- **Publier les notes** : tant que ce n'est pas fait (et sauf si l'option a été cochée à la création), les étudiants
  voient seulement « Copie remise ». L'examen doit être publié et aucune copie en cours. **La publication ne peut pas
  être annulée.**
- **Exporter en Excel**, **Exporter en CSV**, **Imprimer / PDF**.
- La copie d'un étudiant montre le **journal de sécurité** : *Violation*, *Ignoré* (doublon à moins de 3 secondes),
  *Information* (perte de focus, redimensionnement), *Reprise autorisée*.

Le journal est un **indice**, pas une preuve : un navigateur ordinaire ne verrouille pas le poste, et un événement
peut avoir une cause innocente (notification, appel, panne). Entendre l'étudiant avant toute décision.

Les fichiers exportés contiennent des données personnelles : les garder sur un support protégé.

## Fin de vie d'un examen

Sans tentative, **Supprimer l'examen**. Avec des tentatives, **Archiver l'examen** (une fois les copies en cours
terminées). La suppression définitive est réservée à l'administration.
