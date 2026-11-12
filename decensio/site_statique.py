"""Export d'une version statique du tableau de bord (GitHub Pages, clé USB, présentation hors ligne).

Le site produit n'a besoin d'aucun serveur : les réponses de l'API sont figées dans des
fichiers JSON. Il est en lecture seule.

À n'utiliser qu'avec des données fictives ou anonymisées : tout ce qui est exporté devient public
dès que le site est publié.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.encoders import jsonable_encoder

from .api import app as api
from .db import session

STATIQUE = Path(__file__).resolve().parent / "web" / "static"


def _ecrire(dossier: Path, nom: str, donnees) -> None:
    (dossier / nom).write_text(json.dumps(jsonable_encoder(donnees), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def exporter_site(destination: str | Path, max_doublons: int = 500) -> dict:
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(STATIQUE, destination / "static")
    shutil.copy(STATIQUE / "index.html", destination / "index.html")
    (destination / "static" / "config.js").write_text(
        'window.DECENSIO = { api: "", statique: true };\n', encoding="utf-8"
    )
    (destination / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages : servir les fichiers tels quels

    donnees = destination / "donnees"
    donnees.mkdir()
    with session() as s:
        _ecrire(donnees, "resume.json", api.resume(s=s))
        _ecrire(donnees, "niveaux.json", api.niveaux(s=s))
        _ecrire(donnees, "couverture.json", api.couverture(niveau=None, s=s))
        _ecrire(donnees, "zones.geojson", api.zones_geojson(niveau=None, s=s))
        _ecrire(donnees, "doublons.json", api.doublons(statut="tous", niveau=None, limite=max_doublons, decalage=0, s=s))
        _ecrire(donnees, "menages-en-double.json", api.menages_en_double(s=s))
        _ecrire(donnees, "anomalies.json", api.anomalies(statut="toutes", gravite=None, type=None, agent=None, limite=2000, decalage=0, s=s))
        _ecrire(donnees, "agents.json", api.agents(s=s))
    fichiers = sorted(p.name for p in donnees.iterdir())
    return {"dossier": str(destination), "fichiers": fichiers}
