# Gold Digger — WoW Forever

Application Streamlit en français : comparaison des bénéfices PNJ, HDV et désenchantement estimés pour une fabrication, classement par rentabilité ou po/min, et achats de composants optimisés entre l’hôtel des ventes et les marchands.

## Lancer l’application

Python **3.14** recommandé (version testée), avec SQLite 3.37+ (tables STRICT).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Ouvrir http://localhost:8501. L’export `data/input/export_hdv.csv` est chargé par défaut. Un autre export peut être importé pour la session. En local, l’application fonctionne sans accès au réseau. En hébergement cloud, les CSV importés sont transmis au serveur pour le calcul ; l’application ne les écrit pas sur disque.

- Noms français des objets et recettes, liens **Wowhead Forever en français** pour chaque objet fabriqué, composant et outil identifié.
- Filtres par métier, compétences minimale et maximale requises pour apprendre la recette, recherche dans les recettes/composants et rentabilité minimale.
- Les compétences inconnues sont exclues par défaut ; une case permet de les inclure explicitement. Le seuil jaune n’est jamais assimilé à un seuil d’apprentissage.
- Liste complète des composants directs pour une fabrication, outils réutilisables, plan d’achats distinguant HDV et marchand, surplus de lots et exports CSV.
- Tri initial par rentabilité ; bénéfice par fabrication et **bénéfice net en or/minute PNJ, HDV et désenchantement** disponibles comme tris secondaires.
- Durée par fabrication, filtre sur les durées connues et provenance des durées dans le détail.

Le filtre **Types de recette** utilise en priorité les classes et sous-classes d’objets du catalogue client Forever, stockées dans SQLite, puis la colonne facultative `type` de l’export HDV en secours : équipement, composants, nourriture et boissons, potions, bandages, sacs, munitions, etc. Une recette à plusieurs résultats peut appartenir à plusieurs catégories. Les catégories absentes restent **Non renseigné** ; elles ne sont pas devinées à partir du métier ou des composants. Les types sont présentés en cases à cocher, toutes cochées par défaut. Les types cochés sont combinés avec OU et restent cumulables avec la recherche et la plage de compétence. Tout décocher masque toutes les recettes.

## Calcul des achats et de la rentabilité

Les prix et achats sont des **entiers en cuivre** ; les espérances de désenchantement conservent les fractions de cuivre jusqu’à l’affichage. L’export HDV doit être en UTF-8, séparateur `;`, avec `id`, `name`, `npc`, `first`, `quantity`, `min`. Les prix du CSV sont en or par unité ; `first` fournit les paliers `prixxquantité`. `npc` représente uniquement le **prix de revente** au PNJ.

Pour chaque composant, le moteur compare les paliers HDV avec le tarif marchand sélectionné. Il peut combiner des unités moins chères à l’HDV avec des achats marchands. Seules les offres **explicitement à stock illimité**, payables en pièces, sont utilisées. Les prix d’achat ne sont jamais déduits des prix de revente.

Les lots marchands sont indivisibles : un besoin de deux fioles peut imposer l’achat de cinq. Le coût du lot entier est compté ; le surplus est affiché sans revenu fictif. Les points de rupture des paliers suffisent à trouver le coût exact du mélange HDV/lots pour une quantité donnée. L’interface évalue exactement une fabrication par recette, y compris les pertes. Le tri ne modifie pas la quantité évaluée.

**Rentabilité PNJ (%) = (revente PNJ − coût des achats pour une fabrication) / coût des achats × 100.** Toutes les quantités produites par cette fabrication sont incluses. Les bénéfices PNJ et HDV estimés, ainsi que leurs débits en po/min, portent sur cette seule fabrication.

Le filtre **Rentables** inclut les recettes bénéficiaires au PNJ, à l’HDV ou par désenchantement. **Rentables HDV**, **Rentables PNJ** et **Rentables désenchantement** permettent de sélectionner un canal. Le seuil et le tri en pourcentage utilisent le meilleur taux connu des trois canaux, ou celui du canal sélectionné. Un prix PNJ nul ou absent ne bloque pas le calcul HDV ou désenchantement. Un prix HDV absent reste une donnée inconnue, jamais une perte présumée.

L’interface calcule une fabrication par recette. Le stock doit suffire pour celle-ci ; les lots marchands nécessaires sont payés entiers, sans amortir leur surplus sur des fabrications futures.

Le mode marchand **prudent** retient le plus haut prix unitaire observé pour un composant. Le mode « meilleur prix observé » est également disponible. Les observations peuvent dépendre de la réputation et de l’accès au vendeur : le nom du marchand et la source figurent dans les achats. Aucune remise personnelle supplémentaire n’est supposée.

Les recettes sont indépendantes : leurs bénéfices et stocks ne s’additionnent pas. L’apprentissage, l’achat initial des outils, les bonus personnels et les déplacements ne sont pas inclus. Les composants intermédiaires sont achetés directement, pas fabriqués récursivement. Les résultats aléatoires non documentés et les constructions de camp restent exclus.

## Durées et bénéfice en or/minute

Choisir **« Bénéfice PNJ (po/min) »** dans « Trier par ». Le tri en pourcentage reste le choix initial. Les lignes sans durée connue restent en fin de classement ; la case « Durée de fabrication connue uniquement » permet de les masquer.

**Or/minute = bénéfice net par fabrication en cuivre × 6 / durée de référence en millisecondes.** Sans délai connu, la durée est celle d’une fabrication ; plusieurs objets produits ne multiplient pas le temps. Avec un délai connu, la durée de référence est le maximum du temps de fabrication et du délai de récupération. Le temps de vente à l’HDV n’est pas inclus.

Les durées absentes ou instantanées ne donnent aucun débit calculé, jamais un taux infini. Les bonus de vitesse personnels, la latence, les achats, déplacements et ventes sont exclus. Un délai de récupération inconnu ne peut pas être pris en compte. Le débit s’applique seulement aux quantités accessibles : une recette rentable sur six secondes ne garantit pas la même production pendant une minute entière.

Le snapshot `data/sources/craft_timings.json` contient **2 215 durées associées** et les motifs d’absence d’association pour **18 recettes**. Source : [recettes Wowcalc Forever](https://wowcalc.net/en/forever/wiki/professions/tailoring), [méthode et build](https://wowcalc.net/en/how-it-works). Le build de durée **1.60.1.70888** est antérieur au catalogue **1.60.1.71037** : l’import exige une correspondance exacte du sort, des composants et des produits, sans présumer que la vitesse n’a pas changé depuis. Cette provenance distincte est enregistrée dans SQLite et affichée dans l’application. Aucun temps Classic ou forfait générique n’est substitué.

```sh
# Collecter/actualiser les durées puis republier SQLite :
.venv/bin/python -m gold_digger.collect_timings --refresh
.venv/bin/python -m gold_digger.build_database
```

Le lecteur accepte encore les bases versions 2 à 4 (désenchantement indisponible). La reconstruction publie atomiquement la version 5 (qualité, niveau d’objet et tables de désenchantement en plus des classes). Les instantanés de durées ne sont jamais appliqués à une recette dont le build, les composants ou les produits ont changé ; refaire la collecte pour vérifier leur concordance.

## Désenchantement estimé

Les deux nouvelles colonnes affichent le **bénéfice désenchantement estimé en po/min** et les **chances / quantités par objet** de chaque matériau, avec liens Wowhead sur les noms. Le détail fournit les prix HDV, les quantités moyennes par fabrication et un export CSV.

`Valeur brute moyenne = Σ(chance × (quantité min + quantité max) / 2 × prix HDV minimum × objets produits)`.
Le bénéfice déduit la commission HDV paramétrée et le coût optimisé du craft (HDV / lots marchands illimités). Les quantités dans un intervalle sont supposées équiprobables. Le temps est `max(craft + nombre d’objets × désenchantement, cooldown)`. La durée par désenchantement vaut 3 s par défaut ([Wowhead Forever, sort 13262](https://www.wowhead.com/forever/spell=13262/disenchant)) et est modifiable. Un prix de matériau manquant empêche toute estimation partielle du bénéfice ; les chances restent visibles. Une durée de craft inconnue ou instantanée empêche le calcul en po/min.

**Limite des données :** `data/sources/disenchant.json` est un instantané factuel de [Professions_Forever/Data/Disenchant.lua](https://github.com/ProfessionsForever/Professions_Forever/blob/main/Data/Disenchant.lua), blob `400b055fa35a404879d6da45c1a63d8b715f5469`, capturé le 22 novembre 2026. Ses tranches proviennent de `ItemDisenchantLoot` du client Forever **1.60.1.70938** ; ses probabilités, quantités, exceptions et exclusions proviennent de **cmangos/classic-db**, commit `c33f90b8eeb3f8bacb53d5cbfee45075c80b416c` (source GPL-3.0). Elles ne sont pas certifiées sur Forever : l’interface les indique comme estimations héritées de Classic. Les exclusions de cette référence restent à vérifier en jeu ; les tables incomplètes ne sont pas valorisées. Les bonus de camp / de personnage et les conversions d’essences sont exclus. Une moyenne positive ne garantit pas le résultat d’un désenchantement ni une vente à l’HDV.

La reconstruction lit cet instantané avec `--disenchant chemin.json` ; `--refresh` ne l’actualise pas automatiquement. Les tables sont validées (probabilités, tranches disjointes, références), puis associées aux objets par **qualité, classe et niveau d’objet**, jamais par niveau de personnage ou compétence de métier.

## Backend et base de données

L’interface lit **`data/catalog/forever.sqlite` en lecture seule**. Aucun téléchargement ou changement de schéma ne se produit à l’ouverture de l’application.

La base normalisée, version 5, utilise des clés étrangères, contraintes de types, quantités positives, clés uniques et index :

| Table | Contenu |
| --- | --- |
| `items` | Identifiant, noms français/anglais, lien Wowhead et source |
| `professions` | Métiers |
| `recipes` | Recettes, compétence requise, provenance du seuil, délai et exclusions |
| `recipe_items` | Composants, productions et outils avec rôle et quantité |
| `recipe_timings` | Durée de fabrication en millisecondes et source/build distincts |
| `recipe_conditions` | Conditions et installations nécessaires en français |
| `sell_prices` | Prix de revente PNJ, séparés des achats |
| `merchant_offers` | Vendeur, prix et quantité du lot, stock illimité et provenance |
| `disenchant_profiles` | Tables de butin, source/build et niveau de preuve |
| `disenchant_outcomes` | Matériau, probabilité, quantités minimale et maximale |
| `item_disenchant` | Association objet/table, ou motif d’absence de calcul |
| `sources` | URL, build ou intervalle de builds observés et description |
| `metadata` | Version, jeu, locale, date d’import et couverture |

`models.py` définit les modèles métier ; `engine.py` réalise les calculs sans dépendre de l’interface ; `database.py` publie et lit les instantanés ; `presentation.py` prépare filtres et listes de composants.

La reconstruction crée une nouvelle base, vérifie les références et l’intégrité, puis remplace atomiquement la précédente. Un échec conserve la base existante. Le JSON initial reste une source d’import versionnée ; il n’est plus utilisé directement par l’interface.

### Reconstituer ou actualiser

```sh
# Première collecte / actualisation des recettes et prix de revente :
.venv/bin/python -m gold_digger.import_catalog --vendor-limit 2000

# Collecter les durées (cache utilisé sauf --refresh) :
.venv/bin/python -m gold_digger.collect_timings

# Construire la base française depuis le catalogue et les observations marchandes :
.venv/bin/python -m gold_digger.build_database

# Actualiser les sources distantes :
.venv/bin/python -m gold_digger.import_catalog --refresh --vendor-limit 2000
.venv/bin/python -m gold_digger.collect_timings --refresh
.venv/bin/python -m gold_digger.build_database --refresh
```

Les téléchargements sont mis en cache dans `data/cache/endgame`. Les builds des recettes, des index d’objets et des guides doivent correspondre ; sinon la reconstruction refuse de mélanger les versions.

Sources : [recettes et objets français Endgame Tools](https://endgametools.com/fr/wow-forever/professions), [guides de compétence](https://endgametools.com/fr/wow-forever/leveling), [observations marchandes en jeu](https://wow-forever.gg/vendors/).

Le fichier **`data/sources/merchant_offers.json`** est un instantané sourcé, intégré le 21 novembre 2026 : 478 offres sur 53 composants, observées sur les builds 1.60.1.69913 à 1.60.1.70959. Le téléchargement direct de cette source refusait les requêtes HTTP ; les données ont été extraites de sa page publique indexée. `--refresh` ne renouvelle donc pas cet instantané marchand. Il faut fournir un nouveau fichier d’observations avec `--merchants chemin.json` pour le remplacer. Chaque offre conserve l’identifiant d’objet, le vendeur, le prix du lot en cuivre, sa quantité, `unlimited: true` et la ligne source ; les métadonnées communes conservent URL, date et builds observés. Les stocks limités et monnaies spéciales sont exclus.

Cette couverture n’est pas un inventaire exhaustif des marchands actuels. L’absence d’offre signifie « non documenté », pas « jamais vendu ». Les prix de revente du CSV restent prioritaires sur les prix complémentaires de la base.

## Déployer sur Streamlit Community Cloud

Le dépôt contient la base SQLite et un export HDV de démarrage. Aucun secret ni service de base de données externe n’est nécessaire.

1. Ouvrir [Streamlit Community Cloud](https://share.streamlit.io/) et se connecter avec GitHub.
2. Autoriser l’accès au dépôt privé `Skydonia/wow_gold_digger`, puis choisir **Create app** → **Yup, I have an app**.
3. Sélectionner le dépôt `Skydonia/wow_gold_digger`, la branche `main` et le fichier `app.py`.
4. Dans **Advanced settings**, sélectionner **Python 3.14**, la version utilisée pour les tests. Laisser les secrets vides.
5. Choisir éventuellement un sous-domaine disponible, puis cliquer sur **Deploy**. Community Cloud fournit l’URL finale ; aucune URL n’est réservée par le dépôt.

Le serveur écoute sur `0.0.0.0` en mode headless. Les dépendances de production sont fixées aux versions testées ; les dépendances de test sont dans `requirements-dev.txt`. Les caches sont bornés pour limiter la consommation mémoire entre imports. La base est lue depuis le dépôt ; les CSV importés ne sont pas enregistrés durablement. Un redémarrage du serveur recharge l’export de démarrage. Les changements poussés sur `main` sont repris par Community Cloud.

La visibilité du dépôt GitHub et celle de l’application sont distinctes : choisir dans les paramètres Streamlit les personnes autorisées à ouvrir l’application. [Instructions officielles](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --test tests/test_table.cjs
```

Les tests couvrent les calculs monétaires, les paliers HDV, les achats mixtes, les lots et surplus, les stocks illimités, les délais, l’intégrité SQLite, la conservation d’une base après échec, les compétences, les liens et les interactions Streamlit. Le coût optimisé est notamment comparé à une recherche exhaustive sur des scénarios aléatoires reproductibles.


## Audit du 22 novembre 2026

La base active contient 21 983 objets et 2 233 recettes du build Forever 1.60.1.71037. Les noms français/anglais, identifiants et liens Wowhead des objets, ainsi que les composants et produits de toutes les recettes, ont été comparés aux pages Endgame Forever collectées le 22 novembre. C’est une vérification exhaustive de cohérence avec cette source, pas une vérification indépendante de chaque objet sur le serveur de jeu.

Corrections : 46 recettes récupèrent leur produit (dont les transmutations et les fontes de métaux) ; « 9-60 Battery Pack » n’est plus confondu avec un rendement variable. Un nouveau patron, Cache-sabots de centaure, et deux objets ont été ajoutés depuis la source actualisée. Les prix PNJ complémentaires et les offres marchandes sont conservés.

28 seuils ont été recoupés sur les fiches et tables **Wowhead Forever** : 9 valeurs corrigées, 12 valeurs manquantes renseignées et 7 confirmations. Les 276 autres compétences non documentées restent inconnues. Les références Classic de Wowcalc et les seuils jaunes ne sont pas substitués aux exigences d’apprentissage Forever. Les divergences non tranchées sont consignées dans le rapport.

Les révisions sont conservées dans `data/sources/skill_reviews.json` avec URL, date, justification et signature de recette. `build_database` les applique après import ; un changement de build, composants, produits ou valeur source inattendue interrompt la reconstruction et impose une nouvelle vérification. L’accès direct HTML à Wowhead a renvoyé HTTP 403 : les vérifications utilisent les fiches et résultats accessibles via la recherche, dont les dates d’indexation varient. Les commentaires historiques ne servent pas de preuve.

Rapport détaillé : `data/audits/2026-11-22/report.json`. Corrections : `corrections.csv` dans le même dossier. Niveaux inconnus : `competences_inconnues.csv`. Les fichiers `.before` permettent de retrouver les anciens instantanés.

Pour reproduire le contrôle :

```sh
.venv/bin/python -m gold_digger.audit_database --before data/audits/2026-11-22/forever.sqlite.before --after data/catalog/forever.sqlite --cache data/cache/audit-2026-11-22 --output data/audits/2026-11-22/report.json
```


Les champs `items.class_id`, `subclass_id` et `inventory_type` viennent de l’index français Endgame Forever ; leur format est documenté dans son script public `/fr/wow-forever/items/search.js` et recoupé avec l’index anglais. Les regroupements de l’interface restent des choix de présentation : classes Arme (2) et Armure (4) → Équipement. Une absence du scan ou un champ CSV vide ne rend plus inconnu un type documenté dans le catalogue. Les objets 7915 et 3484 sont tous deux de classe 4, sous-classe 3 (mailles), conformément à leurs fiches Wowhead Forever.
