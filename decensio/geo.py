"""Outils géographiques : chargement des zones, rattachement d'un point GPS à sa zone, distances."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from shapely import STRtree
from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

RAYON_TERRE_M = 6_371_008.8


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau (formule de haversine), en mètres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(a))


def superficie_km2(geom: BaseGeometry) -> float:
    """Superficie approchée d'une géométrie en degrés (projection équivalente locale)."""
    if geom.is_empty:
        return 0.0
    lat0 = math.radians(geom.centroid.y)
    kx = RAYON_TERRE_M * math.cos(lat0) * math.pi / 180
    ky = RAYON_TERRE_M * math.pi / 180
    projetee = transform(lambda x, y, z=None: (x * kx, y * ky), geom)
    return projetee.area / 1e6


def valider_coordonnees(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


@dataclass
class EntiteZone:
    code: str
    nom: str
    niveau: str
    code_parent: str | None
    geometrie: BaseGeometry


def _premiere_valeur(proprietes: dict, champs: Iterable[str]) -> str | None:
    minuscules = {k.lower(): v for k, v in proprietes.items()}
    for champ in champs:
        valeur = minuscules.get(champ.lower())
        if valeur not in (None, ""):
            return str(valeur)
    return None


# Noms de champs rencontrés dans les fichiers GRID3, OCHA/HDX et INS.
CHAMPS_CODE = ["code", "pcode", "id", "zs_code", "as_code", "adm3_pcode", "adm2_pcode", "code_zone", "uid"]
CHAMPS_NOM = ["nom", "name", "zs_nom", "as_nom", "adm3_fr", "adm2_fr", "adm3_name", "adm2_name", "quartier", "commune"]
CHAMPS_PARENT = ["code_parent", "parent", "parent_code", "commune_code"]


def lire_zones(
    chemin: str | Path,
    niveau: str = "quartier",
    champ_code: str | None = None,
    champ_nom: str | None = None,
    champ_parent: str | None = None,
) -> list[EntiteZone]:
    """Lit un fichier de limites (GeoJSON ; Shapefile ou GeoPackage si pyogrio est installé)."""
    chemin = Path(chemin)
    if chemin.suffix.lower() in {".geojson", ".json"}:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        entites = donnees["features"] if donnees.get("type") == "FeatureCollection" else [donnees]
    else:
        try:
            import pyogrio  # type: ignore
        except ImportError as exc:  # pragma: no cover - dépend de l'installation
            raise RuntimeError(
                "Pour lire un Shapefile ou un GeoPackage, installez pyogrio (pip install pyogrio) "
                "ou convertissez le fichier en GeoJSON (QGIS, mapshaper.org)."
            ) from exc
        entites = json.loads(pyogrio.read_dataframe(chemin).to_crs(4326).to_json())["features"]

    resultat: list[EntiteZone] = []
    for i, entite in enumerate(entites, start=1):
        props = entite.get("properties") or {}
        geom = shape(entite["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        code = props.get(champ_code) if champ_code else _premiere_valeur(props, CHAMPS_CODE)
        nom = props.get(champ_nom) if champ_nom else _premiere_valeur(props, CHAMPS_NOM)
        parent = props.get(champ_parent) if champ_parent else _premiere_valeur(props, CHAMPS_PARENT)
        resultat.append(
            EntiteZone(
                code=str(code or f"Z{i:05d}"),
                nom=str(nom or code or f"Zone {i}"),
                niveau=str(props.get("niveau") or niveau),
                code_parent=str(parent) if parent else None,
                geometrie=geom,
            )
        )
    return resultat


class IndexZones:
    """Index spatial pour retrouver rapidement la zone qui contient un point."""

    def __init__(self, zones: list[tuple[int, BaseGeometry]]):
        self.ids = [z[0] for z in zones]
        self.geometries = [z[1] for z in zones]
        self.arbre = STRtree(self.geometries) if self.geometries else None

    @classmethod
    def depuis_geojson(cls, zones: Iterable[tuple[int, str]]) -> "IndexZones":
        return cls([(zid, shape(json.loads(g))) for zid, g in zones])

    def zone_du_point(self, lat: float | None, lon: float | None) -> int | None:
        if self.arbre is None or not valider_coordonnees(lat, lon):
            return None
        point = Point(lon, lat)
        candidats = self.arbre.query(point, predicate="intersects")
        if len(candidats) == 0:
            return None
        # Si plusieurs zones se chevauchent (limites imprécises), on prend la plus petite.
        meilleur = min(candidats, key=lambda i: self.geometries[i].area)
        return self.ids[int(meilleur)]


def en_geojson(geom: BaseGeometry) -> str:
    return json.dumps(mapping(geom), separators=(",", ":"))
