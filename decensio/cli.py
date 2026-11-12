"""Ligne de commande : decensio <commande> …

Exemples :
    decensio init
    decensio zones limites_quartiers.geojson --niveau quartier
    decensio population cod_pop_grid3.tif --source "GRID3 v4.4"
    decensio importer export_cspro.csv --source cspro
    decensio recalculer
    decensio couverture
    decensio serveur
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import select

from . import __version__
from .config import parametres
from .db import initialiser_base, session
from .ingest import lire_csv, lire_json
from .models import CouvertureZone, Zone
from .services import (
    importer_estimations_csv,
    importer_grille,
    importer_menages,
    importer_zones,
    journaliser,
    recalculer,
)


def _acteur() -> str:
    try:
        return "cli:" + getpass.getuser()
    except Exception:  # pragma: no cover
        return "cli"


def _afficher(donnees: dict) -> None:
    print(json.dumps(donnees, ensure_ascii=False, indent=2, default=str))


def cmd_init(_: argparse.Namespace) -> None:
    initialiser_base()
    print("Base de données prête.")


def cmd_zones(a: argparse.Namespace) -> None:
    initialiser_base()
    with session() as s:
        r = importer_zones(s, a.fichier, a.niveau, a.champ_code, a.champ_nom, a.champ_parent)
        journaliser(s, _acteur(), "import_zones", Path(a.fichier).name, r)
    _afficher(r)


def cmd_population(a: argparse.Namespace) -> None:
    initialiser_base()
    with session() as s:
        r = importer_grille(s, a.grille, a.source, a.niveau, a.date)
        journaliser(s, _acteur(), "import_grille", Path(a.grille).name, r)
    _afficher(r)


def cmd_estimations(a: argparse.Namespace) -> None:
    initialiser_base()
    with session() as s:
        r = importer_estimations_csv(s, a.fichier, a.source, a.date)
        journaliser(s, _acteur(), "import_estimations", Path(a.fichier).name, {k: v for k, v in r.items() if k != "codes_inconnus"})
    _afficher(r)


def cmd_importer(a: argparse.Namespace) -> None:
    initialiser_base()
    p = parametres()
    chemin = Path(a.fichier)
    colonnes = json.loads(Path(a.colonnes).read_text(encoding="utf-8")) if a.colonnes else None
    if chemin.suffix.lower() == ".json":
        menages = lire_json(chemin, p.decalage_horaire)
    else:
        menages = lire_csv(chemin, colonnes, p.decalage_horaire)
    with session() as s:
        lot, _ = importer_menages(s, menages, p, a.source, chemin.name)
        r = {"lot": lot.id, "menages": lot.nb_menages, "personnes": lot.nb_personnes}
        journaliser(s, _acteur(), "import_enregistrements", chemin.name, r)
    _afficher(r)
    if not a.sans_calcul:
        cmd_recalculer(a)


def cmd_recalculer(_: argparse.Namespace) -> None:
    initialiser_base()
    with session() as s:
        r = recalculer(s, parametres())
        journaliser(s, _acteur(), "recalcul", None, r)
    _afficher(r)


def cmd_couverture(a: argparse.Namespace) -> None:
    initialiser_base()
    with session() as s:
        req = select(Zone, CouvertureZone).join(CouvertureZone, CouvertureZone.zone_id == Zone.id)
        if a.niveau:
            req = req.where(Zone.niveau == a.niveau)
        lignes = s.execute(req.order_by(CouvertureZone.taux)).all()
    if not lignes:
        print("Aucun résultat : lancez « decensio recalculer ».")
        return
    print(f"{'Code':<14}{'Zone':<26}{'Attendus':>10}{'Uniques':>10}{'Taux':>8}  Statut")
    for z, c in lignes:
        attendus = f"{c.population_estimee:,.0f}".replace(",", " ") if c.population_estimee is not None else "—"
        taux = f"{c.taux * 100:.0f} %" if c.taux is not None else "—"
        print(f"{z.code:<14}{z.nom[:25]:<26}{attendus:>10}{c.personnes_uniques:>10}{taux:>8}  {c.statut}")


def cmd_serveur(a: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("decensio.api.app:app", host=a.hote, port=a.port, reload=a.reload)


def cmd_donnees_test(a: argparse.Namespace) -> None:
    from .synthetique import generer

    _afficher(generer(a.dossier, a.graine))
    print(f"Fichiers écrits dans {a.dossier} : zones.geojson, population.tif, enregistrements.csv")


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="decensio", description="Decensio : couverture et contrôle qualité du recensement et de l'identification.")
    p.add_argument("--version", action="version", version=f"decensio {__version__}")
    sp = p.add_subparsers(dest="commande", required=True)

    sp.add_parser("init", help="crée les tables de la base de données").set_defaults(fn=cmd_init)

    z = sp.add_parser("zones", help="importe des limites de zones (GeoJSON)")
    z.add_argument("fichier")
    z.add_argument("--niveau", default="quartier", help="province, commune, zone_sante, aire_sante, quartier…")
    z.add_argument("--champ-code")
    z.add_argument("--champ-nom")
    z.add_argument("--champ-parent")
    z.set_defaults(fn=cmd_zones)

    g = sp.add_parser("population", help="calcule la population attendue par zone à partir d'une grille GRID3/WorldPop (GeoTIFF)")
    g.add_argument("grille")
    g.add_argument("--source", default="GRID3")
    g.add_argument("--niveau", help="limiter le calcul aux zones de ce niveau")
    g.add_argument("--date", help="date de référence de l'estimation (ex. 2025-12)")
    g.set_defaults(fn=cmd_population)

    e = sp.add_parser("estimations", help="importe des estimations par zone depuis un CSV (code_zone ; population)")
    e.add_argument("fichier")
    e.add_argument("--source", required=True, help="ex. RGPH-2, INS 2026")
    e.add_argument("--date")
    e.set_defaults(fn=cmd_estimations)

    i = sp.add_parser("importer", help="importe des ménages et personnes enregistrés (CSV ou JSON)")
    i.add_argument("fichier")
    i.add_argument("--source", default="csv", help="ex. cspro, onip, kobo")
    i.add_argument("--colonnes", help="fichier JSON de correspondance des colonnes {champ: colonne}")
    i.add_argument("--sans-calcul", action="store_true", help="ne pas recalculer doublons, anomalies et couverture")
    i.set_defaults(fn=cmd_importer)

    sp.add_parser("recalculer", help="recalcule doublons, saisies suspectes et couverture").set_defaults(fn=cmd_recalculer)

    c = sp.add_parser("couverture", help="affiche la couverture par zone")
    c.add_argument("--niveau")
    c.set_defaults(fn=cmd_couverture)

    s = sp.add_parser("serveur", help="lance l'API et le tableau de bord")
    s.add_argument("--hote", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serveur)

    t = sp.add_parser("donnees-test", help="génère des données fictives pour essayer Decensio")
    t.add_argument("dossier")
    t.add_argument("--graine", type=int, default=7)
    t.set_defaults(fn=cmd_donnees_test)
    return p


def main(argv: list[str] | None = None) -> None:
    args = construire_parseur().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
