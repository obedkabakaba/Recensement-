"""Données de test réalistes (fictives) pour essayer Decensio sans données réelles.

Produit, dans un dossier :
- zones.geojson      : une commune fictive découpée en quartiers ;
- population.tif     : une grille de population (cellules d'environ 100 m), au format GRID3 ;
- enregistrements.csv: des ménages enregistrés, avec des doublons et des anomalies volontaires.

Toutes les personnes sont inventées. Aucune donnée réelle n'est utilisée.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

NOMS = [
    "Kabasele", "Tshibangu", "Ilunga", "Kasongo", "Mbuyi", "Mukendi", "Kalonji", "Mwamba", "Nkulu", "Lukusa",
    "Nzuzi", "Mutombo", "Ngalula", "Kanku", "Nsimba", "Mbala", "Makiadi", "Lumbu", "Kabeya", "Tshilombo",
    "Kitenge", "Banza", "Mpiana", "Nlandu", "Diakiese", "Matondo", "Kiese", "Bokolo", "Lokwa", "Mayala",
    "Kabamba", "Kalala", "Kazadi", "Kayembe", "Ngoy", "Numbi", "Mulumba", "Tshimanga", "Badibanga", "Kapinga",
    "Mbombo", "Ntumba", "Bakajika", "Kabongo", "Kalombo", "Kanyinda", "Katende", "Kasanda", "Lusamba", "Mbiya",
    "Misenga", "Mpoyi", "Mujinga", "Mukuna", "Musau", "Mutamba", "Nkongolo", "Tshiama", "Kongolo", "Lubaki",
    "Makengo", "Malu", "Mampuya", "Masamba", "Matadi", "Mavungu", "Mbemba", "Mbuta", "Mfumu", "Mpanzu",
    "Ndombe", "Nkanga", "Ntoto", "Nzinga", "Phambu", "Vangu", "Wamba", "Bolamba", "Bosenge", "Bompende",
    "Ekofo", "Elonga", "Isomi", "Liyolo", "Lokele", "Mongala", "Mputu", "Ndjoli", "Ngandu", "Ngoma",
    "Nkoy", "Bahati", "Baraka", "Furaha", "Mapendo", "Neema", "Amani", "Kahindo", "Kambale", "Kasereka",
    "Paluku", "Muhindo", "Kavira", "Masika", "Mumbere", "Kakule", "Byamungu", "Bisimwa", "Cirhuza", "Mugisho",
]
PRENOMS_H = [
    "Jean", "Patrick", "Joseph", "Pierre", "Christian", "Junior", "Bienvenu", "Héritier", "Glody", "Trésor",
    "Fiston", "Daniel", "Emmanuel", "Jonathan", "Benjamin", "Samuel", "David", "Moïse", "Josué", "Gédéon",
    "Dieudonné", "Blaise", "Cédric", "Arsène", "Serge", "Fabrice", "Hervé", "Guelord", "Exaucé", "Plamedi",
    "Prince", "Merdi", "Destin", "Espoir", "Israël", "Nathan", "Aaron", "Caleb", "Élie", "Paul",
    "André", "Michel", "Didier", "Olivier", "Alain", "Eric", "Thierry", "Papy", "Rodrigue", "Jérémie",
]
PRENOMS_F = [
    "Marie", "Grâce", "Christelle", "Esther", "Rachel", "Sarah", "Ruth", "Merveille", "Nadège", "Gloria",
    "Divine", "Chancelle", "Exaucée", "Gracia", "Bénédicte", "Dorcas", "Déborah", "Naomie", "Rebecca", "Miriam",
    "Jemima", "Prisca", "Lydia", "Joëlle", "Patience", "Bénie", "Plamedie", "Princesse", "Gladys", "Sandrine",
    "Francine", "Mireille", "Annie", "Clarisse", "Nathalie", "Vanessa", "Ornella", "Josiane", "Arlette", "Fanny",
    "Charlotte", "Élodie", "Agnès", "Sylvie", "Jeanne", "Odette", "Pauline", "Rosette", "Solange", "Thérèse",
]

VARIANTES = {
    "Tshibangu": "Tchibangu", "Ilunga": "Ilounga", "Kasongo": "Kassongo", "Kalonji": "Kalondji",
    "Mwamba": "Mouamba", "Kabasele": "Kabaselle", "Mbuyi": "Mbuyie", "Nkulu": "Nkoulou", "Lukusa": "Loukoussa",
    "Nzuzi": "Nzouzi", "Mukendi": "Moukendi", "Tshilombo": "Chilombo",
}

# Emprise de la commune fictive (près de Kinshasa).
LON0, LAT0 = 15.360, -4.420
COLS, LIGNES = 4, 3
PAS = 0.010  # environ 1,1 km par quartier
CELLULE = 0.000833  # environ 100 m


def _zones() -> dict:
    entites = []
    commune = [[LON0, LAT0], [LON0 + COLS * PAS, LAT0], [LON0 + COLS * PAS, LAT0 + LIGNES * PAS], [LON0, LAT0 + LIGNES * PAS], [LON0, LAT0]]
    entites.append({"type": "Feature", "properties": {"code": "CT", "nom": "Commune fictive", "niveau": "commune"},
                    "geometry": {"type": "Polygon", "coordinates": [commune]}})
    n = 1
    for j in range(LIGNES):
        for i in range(COLS):
            x0, y0 = LON0 + i * PAS, LAT0 + j * PAS
            anneau = [[x0, y0], [x0 + PAS, y0], [x0 + PAS, y0 + PAS], [x0, y0 + PAS], [x0, y0]]
            entites.append({"type": "Feature", "properties": {"code": f"CT-Q{n:02d}", "nom": f"Secteur fictif {n}", "code_parent": "CT"},
                            "geometry": {"type": "Polygon", "coordinates": [anneau]}})
            n += 1
    return {"type": "FeatureCollection", "features": entites}


def _grille(chemin: Path, rng: np.random.Generator, echelle: float = 1.0) -> np.ndarray:
    largeur = int(round(COLS * PAS / CELLULE))
    hauteur = int(round(LIGNES * PAS / CELLULE))
    # Densité variable : un centre dense et des quartiers plus clairsemés.
    yy, xx = np.mgrid[0:hauteur, 0:largeur]
    centre = np.exp(-(((xx - largeur * 0.35) / (largeur * 0.35)) ** 2 + ((yy - hauteur * 0.5) / (hauteur * 0.6)) ** 2))
    pop = (8 + 60 * centre) * rng.uniform(0.6, 1.4, size=(hauteur, largeur))
    pop = (pop * echelle).astype("float32")
    transformation = from_origin(LON0, LAT0 + LIGNES * PAS, CELLULE, CELLULE)
    with rasterio.open(chemin, "w", driver="GTiff", height=hauteur, width=largeur, count=1, dtype="float32",
                       crs="EPSG:4326", transform=transformation, nodata=-99999) as dst:
        dst.write(pop, 1)
    return pop


def _personne(rng: random.Random, nom: str, sexe: str, age: int, lien: str, deja: set[str]) -> dict:
    # Deux enfants d'un même ménage ne portent pas le même prénom.
    prenom = rng.choice([p for p in (PRENOMS_H if sexe == "M" else PRENOMS_F) if p not in deja])
    deja.add(prenom)
    postnom = rng.choice(NOMS)
    annee = 2026 - age
    date_n = f"{annee}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}" if rng.random() < 0.6 else ""
    return {"nom": nom, "postnom": postnom, "prenom": prenom, "sexe": sexe, "age": age, "date_naissance": date_n, "lien": lien}


def _menage(rng: random.Random) -> list[dict]:
    nom = rng.choice(NOMS)
    sexe_chef = "M" if rng.random() < 0.75 else "F"
    age_chef = rng.randint(24, 68)
    deja: set[str] = set()
    membres = [_personne(rng, nom, sexe_chef, age_chef, "chef", deja)]
    if rng.random() < 0.7:
        membres.append(_personne(rng, rng.choice(NOMS), "F" if sexe_chef == "M" else "M", max(18, age_chef - rng.randint(0, 8)), "conjoint", deja))
    for _ in range(rng.randint(0, 6)):
        membres.append(_personne(rng, nom, rng.choice("MF"), rng.randint(0, max(1, age_chef - 16)), "enfant", deja))
    return membres


def generer(dossier: str | Path, graine: int = 7, taux_couverture: dict[int, float] | None = None, echelle: float = 1.0) -> dict:
    """Écrit les trois fichiers de test dans `dossier` et renvoie un résumé de ce qui a été injecté.

    `echelle` réduit la population (0,1 = dix fois moins d'habitants) pour des essais rapides.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    rng = random.Random(graine)
    nrng = np.random.default_rng(graine)

    (dossier / "zones.geojson").write_text(json.dumps(_zones()), encoding="utf-8")
    pop = _grille(dossier / "population.tif", nrng, echelle)

    # Part des habitants déjà enregistrés, par quartier (1 à 12). Certains quartiers sont en retard.
    taux_couverture = taux_couverture or {1: 0.95, 2: 0.92, 3: 0.55, 4: 0.97, 5: 0.93, 6: 0.30, 7: 0.80, 8: 0.96, 9: 0.94, 10: 0.0, 11: 0.75, 12: 0.91}
    hauteur, largeur = pop.shape
    lignes: list[dict] = []
    agents = [f"AG{n:03d}" for n in range(1, 9)]
    debut = datetime(2026, 9, 1, 8, 0)
    horloges = {a: debut for a in agents}
    compteur = 0
    menages_crees: list[tuple[str, dict, list[dict]]] = []

    for q in range(1, COLS * LIGNES + 1):
        i, j = (q - 1) % COLS, (q - 1) // COLS
        # Cellules du quartier dans la grille (ligne 0 = nord).
        c0, c1 = int(round(i * PAS / CELLULE)), int(round((i + 1) * PAS / CELLULE))
        l1 = hauteur - int(round(j * PAS / CELLULE))
        l0 = hauteur - int(round((j + 1) * PAS / CELLULE))
        attendus = float(pop[l0:l1, c0:c1].sum())
        a_enregistrer = attendus * taux_couverture.get(q, 0.9)
        agent = agents[(q - 1) % len(agents)]
        personnes = 0
        while personnes < a_enregistrer:
            compteur += 1
            membres = _menage(rng)
            lat = LAT0 + j * PAS + rng.uniform(0.0005, PAS - 0.0005)
            lon = LON0 + i * PAS + rng.uniform(0.0005, PAS - 0.0005)
            horloges[agent] += timedelta(minutes=rng.randint(12, 25))
            if horloges[agent].hour >= 17:
                horloges[agent] = horloges[agent].replace(hour=8, minute=0) + timedelta(days=1)
            entete = {"menage_id": f"M{compteur:06d}", "agent_id": agent, "date_collecte": horloges[agent].strftime("%Y-%m-%d %H:%M:%S"),
                      "latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}", "precision_gps": rng.choice([4, 6, 8, 10, 12]),
                      "zone_assignee": f"CT-Q{q:02d}", "taille_menage": len(membres)}
            menages_crees.append((f"CT-Q{q:02d}", entete, membres))
            personnes += len(membres)

    injecte = {"menages_en_double": 0, "empilement_gps": 0, "rythme_rapide": 0, "hors_zone": 0, "ages_invraisemblables": 0}

    # 1) Ménages visités deux fois par un autre agent, avec des variantes d'orthographe.
    for zone, entete, membres in rng.sample(menages_crees, min(25, len(menages_crees) // 4)):
        compteur += 1
        copie = []
        for p in membres:
            p2 = dict(p)
            p2["nom"] = VARIANTES.get(p["nom"], p["nom"])
            if rng.random() < 0.5:
                p2["date_naissance"] = ""  # l'agent n'a noté que l'âge
            copie.append(p2)
        e2 = dict(entete, menage_id=f"M{compteur:06d}", agent_id="AG099",
                  latitude=f"{float(entete['latitude']) + rng.uniform(-0.0002, 0.0002):.6f}",
                  longitude=f"{float(entete['longitude']) + rng.uniform(-0.0002, 0.0002):.6f}",
                  date_collecte=(datetime.strptime(entete["date_collecte"], "%Y-%m-%d %H:%M:%S") + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"))
        menages_crees.append((zone, e2, copie))
        injecte["menages_en_double"] += 1

    # 2) Un agent qui saisit des ménages depuis un seul endroit, très vite, hors horaires.
    t = datetime(2026, 9, 2, 22, 10)
    for k in range(8):
        compteur += 1
        membres = _menage(rng)
        t += timedelta(seconds=70)
        entete = {"menage_id": f"M{compteur:06d}", "agent_id": "AG050", "date_collecte": t.strftime("%Y-%m-%d %H:%M:%S"),
                  "latitude": f"{LAT0 + 0.0151:.6f}", "longitude": f"{LON0 + 0.0251 + k * 0.000005:.6f}", "precision_gps": 5,
                  "zone_assignee": "CT-Q07", "taille_menage": len(membres)}
        menages_crees.append(("CT-Q07", entete, membres))
    injecte["empilement_gps"] = 1
    injecte["rythme_rapide"] = 7

    # 3) Un ménage enregistré loin de sa zone assignée, et des âges invraisemblables.
    zone, entete, membres = menages_crees[3]
    entete["zone_assignee"] = "CT-Q12"
    injecte["hors_zone"] = 1
    for _, _, membres in rng.sample(menages_crees, 3):
        membres[-1]["age"] = 134
        membres[-1]["date_naissance"] = ""
        injecte["ages_invraisemblables"] += 1

    champs = ["menage_id", "agent_id", "date_collecte", "latitude", "longitude", "precision_gps", "zone_assignee", "taille_menage",
              "rang", "nom", "postnom", "prenom", "sexe", "date_naissance", "age", "lien"]
    with open(dossier / "enregistrements.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs, delimiter=";")
        w.writeheader()
        for _, entete, membres in menages_crees:
            for rang, p in enumerate(membres, start=1):
                w.writerow({**entete, "rang": rang, **p})

    return {"menages": len(menages_crees), "personnes": sum(len(m) for _, _, m in menages_crees), **injecte}
