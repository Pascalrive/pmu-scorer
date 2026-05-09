# PATCH v14 -> v15 : passage en mode 100% gratuit

## Resume

La v15 remplace l'API Claude (couteuse) par du scraping direct des memes
sites de pronostics. **Cout: 0 EUR/mois au lieu de ~360 EUR.**

## Fichiers a modifier

### 1. Ajouter un fichier
Copier `pronos_gratuit.py` a cote de `pmu_scorer.py`.

### 2. Installer les 2 dependances (si pas deja la)
```bash
pip install requests beautifulsoup4
```

### 3. Modifier `pmu_scorer.py`

**a) En haut du fichier, remplacer l'import Anthropic :**

```python
# AVANT (v14)
import anthropic
client = anthropic.Anthropic(api_key=API_KEY)

# APRES (v15)
from pronos_gratuit import get_pronostics_gratuit
```

**b) Remplacer la fonction `get_pronostics_claude()` :**

```python
# AVANT (v14) - environ 80 lignes avec retry, parsing JSON, etc.
def get_pronostics_claude(...):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        ...
    )
    ...

# APRES (v15) - 1 ligne
def get_pronostics(date_str, reunion, course, nom, partants):
    return get_pronostics_gratuit(date_str, reunion, course, nom, partants)
```

**c) Supprimer le `time.sleep(60)` entre courses**
Le scraping a son propre delai (0.6s) integre, et le cache fait que
les pages communes (Geny reperes, Zone-Turf) ne sont fetchees qu'une fois.

**d) Adapter l'appel** dans la boucle de scoring : la cle des scores
n'est plus 'sources_count' mais 'nb_sources', et 'consensus' devient
'scores'. Voir `mapping_v14_v15.md`.

## Mapping des cles de retour

| v14 (Claude API)        | v15 (gratuit)        |
|-------------------------|----------------------|
| `sources_count`         | `nb_sources`         |
| `consensus`             | `scores`             |
| `synthese`              | `details`            |
| `outsider_surprise`     | (calcule en interne) |

## Test avant prod

```bash
cd /chemin/vers/pmu_scorer
python pronos_gratuit.py
# Doit afficher des scores pour INEXESS BLEU et INO DU LUPIN
```

## Pondre/depondre les sources

Editer la constante `POIDS_SOURCES` en tete de `pronos_gratuit.py` :

```python
POIDS_SOURCES = {
    "geny_reperes": 25,    # augmenter si tu fais confiance
    "geny_course":  20,
    "zone_turf":    20,
    "canalturf":    20,
    "equidia":      15,
}
```

## Limites connues

- Pas de cache disque entre runs (uniquement en memoire). Si le script
  tombe et redemarre, il re-scrape tout. Acceptable car c'est gratuit.
- Heuristique "rang 1 partout" sur certaines sources (Zone-Turf,
  Canalturf, Equidia) car le HTML ne distingue pas le N1 du N2 sans
  parser plus finement la structure DOM. A ameliorer en v15.1 si le
  bilan le justifie.
- Pas de fallback Claude. Si tous les scrapers tombent (rare, cela
  voudrait dire les 5 sites HS en meme temps), `nb_sources=0` et le
  scoring tombe en mode degrade comme dans la v14.

## Bonus

Ajoute un mode `--no-network` pour tester en local sans Internet
(utilise des fixtures HTML pre-enregistrees). Optionnel, je peux
te le faire si besoin.
