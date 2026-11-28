# Guide de l'administrateur

Installation : [README](../README.md), [HTTPS](HTTPS.md), [sauvegarde](SAUVEGARDE.md).

## Les comptes d'administration

- Le **super-administrateur** est créé sur le serveur : `python manage.py createsuperuser`
  (avec Docker : `docker compose exec web python manage.py createsuperuser`). Lui seul peut nommer, révoquer ou
  désactiver un administrateur.
- L'**administrateur** gère les comptes, les classes et le cycle de vie des examens.

Après connexion, le menu latéral propose **Administration**, **Comptes** et **Journal**.

## Créer un compte

**Comptes → Créer un compte** : identifiant, prénom, nom, e-mail, mot de passe (8 caractères au moins, ni trop
courant ni trop proche de l'identifiant), rôle. Pour un étudiant, le **matricule** et le **niveau** sont obligatoires,
et un matricule ne peut servir qu'à un seul compte. Un nouvel étudiant est inscrit aux examens déjà publiés pour
son niveau. Transmettre le mot de passe à la personne par un canal sûr.

Les étudiants peuvent aussi créer leur compte eux-mêmes depuis la page de connexion.

## Gérer les comptes

La page **Comptes** permet de chercher (nom, identifiant, e-mail, matricule) et de filtrer par rôle.

| Action | Comment | Limites |
|---|---|---|
| Donner le rôle enseignant | liste **Rôle**, puis **OK** | pas sur son propre compte ni sur un super-administrateur |
| Désactiver / réactiver | bouton de la ligne | le compte désactivé ne peut plus se connecter ; son historique reste |
| Changer un mot de passe oublié | super-administrateur : **Administration technique → Utilisateurs**, ou `python manage.py changepassword identifiant` | vérifier d'abord l'identité de la personne |
| Supprimer un compte | à éviter : désactiver | un compte qui possède des examens, des classes ou des copies ne peut pas être supprimé |

Le lien **Mot de passe oublié ?** de la page de connexion envoie un lien de réinitialisation aux comptes ayant un
e-mail ; il faut pour cela configurer un serveur d'e-mail (voir la
[documentation technique](DOCUMENTATION_TECHNIQUE.md#configuration)).

## Blocage des connexions

Après **5 échecs**, le couple identifiant + adresse IP est bloqué **15 minutes** (`AXES_FAILURE_LIMIT`,
`AXES_COOLOFF_MINUTES`). Pour débloquer tout de suite une personne, après avoir vérifié son identité :

```bash
python manage.py axes_reset_username identifiant   # avec Docker : docker compose exec web python manage.py …
```

Le super-administrateur peut aussi voir et supprimer les tentatives dans `/admin/`, section **Axes**.

## Classes

Le tableau **Classes** de la page Administration montre le propriétaire, le code, les effectifs, et permet
d'**archiver** ou **restaurer** une classe. En ouvrant une classe, l'administrateur dispose des mêmes actions que son
propriétaire. Une classe qui contient des examens ne peut pas être supprimée : l'archiver.

## Cycle de vie des examens

| Situation de l'examen | Action possible |
|---|---|
| Aucune tentative | **Supprimer** |
| Au moins une tentative | **Archiver** : il disparaît chez les étudiants, l'historique est conservé |
| Archivé | **Supprimer définitivement** : télécharger d'abord l'**export CSV**, cocher la case, saisir `SUPPRIMER` |

La suppression définitive efface l'examen, les copies, les réponses et le journal de sécurité. Elle est irréversible
(hors restauration d'une sauvegarde). L'administrateur peut archiver un examen même si des copies sont en cours :
l'examen disparaît alors de l'espace des étudiants, qui ne peuvent plus y revenir depuis leur tableau de bord, mais
une page d'examen déjà ouverte continue de fonctionner. Pour arrêter un examen en cours, ne pas compter sur
l'archivage.

## Journal des opérations

**Journal des opérations** liste qui a fait quoi : comptes créés, rôles modifiés, désactivations, publications,
clôtures, archivages, suppressions, inscriptions, reprises autorisées, etc. La recherche porte sur la personne,
l'action, l'objet et le détail ; 50 lignes par page. Les modifications faites dans l'**Administration technique**
(`/admin/`) sont dans l'historique propre à Django, pas dans ce journal.

## Administration technique (`/admin/`)

Réservée aux comptes « membre de l'équipe » (en pratique le super-administrateur). Les réponses des étudiants, le
journal de sécurité et le journal des opérations y sont en **lecture seule**. Les autres objets sont modifiables sans
les contrôles de l'application : n'y intervenir qu'en cas de nécessité, après une sauvegarde.

## Autour d'un examen

**Avant** : suivre la [checklist](DEPLOYMENT_CHECKLIST.md), vérifier que la clôture automatique est planifiée
(`close_expired_attempts`, chaque minute), faire une sauvegarde, prévoir une procédure en cas de coupure.

**Pendant** : le temps est compté par le serveur et continue pendant une panne côté étudiant. Une reprise se décide
par l'enseignant ou l'administration, uniquement pour une copie clôturée pour raison de sécurité, avec un motif.

**Après** : exporter les résultats, faire une sauvegarde, la mettre à l'abri.
