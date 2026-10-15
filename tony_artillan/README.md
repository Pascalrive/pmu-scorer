# Tony Artillan — simulation independante

Ce programme n'importe aucun module de l'algorithme principal ni du consensus.
Il utilise son dossier de donnees, son bilan, son journal Telegram et son verrou
GitHub Actions. Les secrets Telegram existants designent le canal deja utilise.
Aucun appel a une interface de prise de paris : uniquement lectures PMU et
messages Telegram. Tous les montants sont virtuels.

## Regle confirmee le 15 octobre 2026

- Reunion francaise R1 si elle compte exactement huit courses C1 a C8.
  Sinon, une seule autre reunion francaise a huit courses est admissible ;
  plusieurs candidates ou aucune : pas de choix arbitraire.
- Premier cheval du pronostic **Paris Turf**, sans remplacement par le favori
  des cotes, Geny, Canalturf ou un autre pronostiqueur.
- Simple gagnant PMU INTERNET : 100 EUR au premier pari, puis +100 EUR apres
  chaque perte consecutive. Chaque gain ramene la mise suivante a 100 EUR,
  meme si ce gain ne couvre pas les pertes precedentes.
- Non-partant/remboursement : aucun changement de mise, aucun remplacement.
  Nouvelle journee : remise a 100 EUR, sans report de pertes la veille.
- Huit pertes : 100+200+300+400+500+600+700+800 = **3 600 EUR**.
- La cote indicative ne sert jamais a regler le gain : seul le dividende du
  simple gagnant definitif PMU INTERNET est multiplie par la mise.

## Etat de la source au deploiement

Le 15/10, les deux pages publiques Paris Turf testees depuis GitHub repondent
403 avec « Just a moment... Enable JavaScript and cookies to continue ».
Preuve dans `data/probe/access.json`. Le collecteur n'essaie pas de contourner
cette verification. Aucun acces automatique quotidien aux huit premiers choix
Paris Turf n'est actuellement valide. **Le programme est en attente de source**,
et envoie ce statut sur Telegram au lieu d'inventer des chevaux ou des gains.

Un import quotidien controle est prevu : `inputs/AAAA-MM-JJ.json`. Il exige
les huit premiers choix, l'attribution Paris Turf, l'URL de la source, l'heure
de capture, le numero et le nom du cheval, et l'intitule exact de chaque course.
Exemple de structure dans `input.example.json` (aucun pronostic reel).
L'import complet doit parvenir au programme avant le depart de C1. Il est
archive et fige ; une modification apres import n'ecrase pas les choix du jour.
Un programme/PDF fourni par l'utilisateur peut etre controle et transcrit dans
ce fichier. L'automatisation integrale de la collecte attend une source Paris
Turf quotidiennement accessible ; ce n'est pas une integration deja terminee.

## Suivi avant et apres course

Les huit choix verifies sont presentes avec leur horaire. Une seule mise est
engagee virtuellement a la fois, au plus tot 30 minutes avant le depart, si tous
les paris precedents sont regles et l'identite officielle est concordante.
Chaque decision porte son horodatage et sa mise immuable, avant depart.
Si le rapport precedent manque, aucune mise ne se devine. Si une course part
sans decision valide, elle reste NON_JOUE ; aucun pari retrospectif n'est cree.
Les jours incomplets sont recontroles les jours suivants pour regler les paris
deja engages, sans ajouter des mises apres coup.

`data/AAAA-MM-JJ/state.json` : choix, mises, resultats, cotes relevees, sources,
rapports, recus Telegram ; `rapport.txt` : presentation detaillee ; `officiels/` :
preuves PMU ; `data/BILAN.json` : jours et cumuls financiers separes des autres
programmes. Le score indique victoires/pertes/remboursements, mises et retours,
solde net, ROI du sous-total regle (ou final si complet), mise maximale et
tresorerie minimale observee. Les remboursements sont inclus dans mises et retours.

Telegram est dedoublonne par contenu. Un timeout d'envoi devient UNCERTAIN,
sans renvoi automatique de ce message. Les recus ne contiennent aucun token.
La simulation et ses decisions sont conservees meme si un message echoue ;
le journal distingue donc une decision virtuelle d'une notification recue.

## Execution

```bash
pip install -r tony_artillan/requirements.txt
python -m unittest discover -s tony_artillan/tests -v
python -m tony_artillan.main --dry-run
python -m tony_artillan.main
```

Workflow propre : `.github/workflows/tony_artillan.yml`, toutes les dix minutes
de 06h a 22h59 UTC, et reprise matinale des rapports. Les crons GitHub peuvent
etre retardes : le programme s'abstient si l'heure de depart est depassee.
Seuls les changements de rapport entrainent une nouvelle notification.
