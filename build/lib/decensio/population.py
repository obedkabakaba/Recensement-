"""Population attendue par zone, à partir d'une grille de population (GRID3, WorldPop) ou d'un tableau.

Les grilles GRID3 donnent un nombre estimé d'habitants par cellule d'environ 100 m.
La population d'une zone est la somme des cellules dont le centre tombe dans la zone.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry


@dataclass
class SommeZonale:
    population: float
    cellules: int


def somme_par_zone(chemin_grille: str | Path, geometries: dict[str, BaseGeometry]) -> dict[str, SommeZonale]:
    """Somme des valeurs de la grille dans chaque géométrie (clé = code de zone)."""
    resultats: dict[str, SommeZonale] = {}
    with rasterio.open(chemin_grille) as grille:
        crs_grille = grille.crs
        nodata = grille.nodata
        for code, geom in geometries.items():
            geo = mapping(geom)
            if crs_grille is not None and crs_grille.to_epsg() != 4326:
                geo = transform_geom("EPSG:4326", crs_grille, geo)
            try:
                valeurs, _ = mask(grille, [geo], crop=True, filled=False, all_touched=False)
            except ValueError:
                # La zone ne recoupe pas la grille.
                resultats[code] = SommeZonale(0.0, 0)
                continue
            bande = valeurs[0]
            donnees = np.ma.masked_invalid(bande.astype("float64"))
            if nodata is not None:
                donnees = np.ma.masked_equal(donnees, nodata)
            donnees = np.ma.masked_less(donnees, 0)
            resultats[code] = SommeZonale(float(donnees.sum()) if donnees.count() else 0.0, int(donnees.count()))
    return resultats


@dataclass
class LigneEstimation:
    code_zone: str
    population: float
    borne_basse: float | None = None
    borne_haute: float | None = None


def lire_tableau_estimations(chemin: str | Path) -> list[LigneEstimation]:
    """Lit un CSV d'estimations (colonnes : code_zone ; population ; borne_basse ; borne_haute).

    Sert pour les chiffres qui ne viennent pas d'une grille : résultats du RGPH-2,
    projections de l'INS, chiffres des zones de santé…
    """
    lignes: list[LigneEstimation] = []
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        echantillon = f.read(4096)
        f.seek(0)
        separateur = ";" if echantillon.count(";") > echantillon.count(",") else ","
        for ligne in csv.DictReader(f, delimiter=separateur):
            ligne = {k.strip().lower(): (v or "").strip() for k, v in ligne.items() if k}
            code = ligne.get("code_zone") or ligne.get("code")
            pop = ligne.get("population")
            if not code or not pop:
                continue

            def nombre(v: str | None) -> float | None:
                return float(v.replace(" ", "").replace(",", ".")) if v else None

            lignes.append(
                LigneEstimation(
                    code_zone=code,
                    population=nombre(pop) or 0.0,
                    borne_basse=nombre(ligne.get("borne_basse")),
                    borne_haute=nombre(ligne.get("borne_haute")),
                )
            )
    return lignes
