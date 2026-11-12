from __future__ import annotations

from pathlib import Path

import pytest

from decensio import db
from decensio.config import Parametres, definir_parametres
from decensio.ingest import lire_csv
from decensio.services import importer_grille, importer_menages, importer_zones, recalculer
from decensio.synthetique import generer


@pytest.fixture()
def params(tmp_path: Path) -> Parametres:
    p = Parametres(database_url=f"sqlite:///{tmp_path / 'test.db'}", secret="secret-de-test")
    definir_parametres(p)
    db.initialiser_base(p.database_url)
    return p


@pytest.fixture(scope="session")
def donnees(tmp_path_factory) -> tuple[Path, dict]:
    dossier = tmp_path_factory.mktemp("synthetique")
    resume = generer(dossier, graine=11, echelle=0.15)
    return dossier, resume


@pytest.fixture()
def base_remplie(params: Parametres, donnees) -> tuple[Parametres, dict]:
    dossier, resume = donnees
    with db.session() as s:
        importer_zones(s, dossier / "zones.geojson")
        importer_grille(s, dossier / "population.tif", "GRID3 test")
        importer_menages(s, lire_csv(dossier / "enregistrements.csv"), params, "csv")
        recalculer(s, params)
    return params, resume
