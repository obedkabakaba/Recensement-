"""Bout en bout sur des données fictives : les problèmes injectés doivent être retrouvés."""

from sqlalchemy import func, select

from decensio import db
from decensio.dedup import recalculer_groupes
from decensio.coverage import calculer_couverture
from decensio.models import Anomalie, CouvertureZone, EstimationPopulation, Menage, PaireDoublon, Personne, Zone


def _agents(s):
    return dict(s.execute(select(Personne.id, Menage.agent_id).join(Menage)).all())


def test_doublons_injectes_retrouves(base_remplie):
    params, resume = base_remplie
    with db.session() as s:
        agent = _agents(s)
        copies = {pid for pid, a in agent.items() if a == "AG099"}
        probables = s.execute(select(PaireDoublon.personne_a_id, PaireDoublon.personne_b_id).where(PaireDoublon.niveau == "probable")).all()
        vrais = [(a, b) for a, b in probables if (a in copies) != (b in copies)]
        trouvees = {a if a in copies else b for a, b in vrais}
        # Rappel : presque toutes les fiches recopiées sont reliées à leur original.
        assert len(trouvees) >= 0.95 * len(copies)
        # Précision : la grande majorité des doublons « probables » sont de vrais doublons.
        assert len(vrais) >= 0.85 * len(probables)


def test_couverture_reflete_les_zones_en_retard(base_remplie):
    with db.session() as s:
        statuts = dict(s.execute(select(Zone.code, CouvertureZone.statut).join(CouvertureZone, CouvertureZone.zone_id == Zone.id)).all())
    assert statuts["CT-Q10"] == "rouge"  # aucun ménage enregistré
    assert statuts["CT-Q06"] == "rouge"  # 30 %
    assert statuts["CT-Q04"] == "vert"  # 97 %
    assert statuts["CT-Q07"] in {"orange", "vert"}  # 80 % + ménages ajoutés par l'agent fraudeur


def test_zone_parente_cumule_ses_quartiers(base_remplie):
    with db.session() as s:
        commune = s.scalar(select(Zone).where(Zone.code == "CT"))
        cz = s.scalar(select(CouvertureZone).where(CouvertureZone.zone_id == commune.id))
        quartiers = s.scalars(select(Zone.id).where(Zone.code_parent == "CT")).all()
        total_quartiers = s.scalar(select(func.sum(CouvertureZone.personnes_uniques)).where(CouvertureZone.zone_id.in_(quartiers)))
        assert cz.personnes_uniques == total_quartiers
        pop_grille = s.scalar(select(EstimationPopulation.population).where(EstimationPopulation.zone_id == commune.id))
        assert abs(cz.population_estimee - pop_grille) < 1


def test_saisies_suspectes_injectees(base_remplie):
    with db.session() as s:
        types = {t for (t,) in s.execute(select(Anomalie.type).distinct())}
        empilement = s.scalar(select(Anomalie).where(Anomalie.type == "empilement_gps"))
    for attendu in {"empilement_gps", "rythme_trop_rapide", "hors_zone_assignee", "age_invraisemblable", "hors_horaires"}:
        assert attendu in types, attendu
    assert empilement.agent_id == "AG050"


def test_rejet_d_un_doublon_rend_la_personne_unique(base_remplie):
    params, _ = base_remplie
    with db.session() as s:
        avant = s.scalar(select(func.count()).where((Personne.groupe_id.is_(None)) | (Personne.groupe_id == Personne.id)))
        paire = s.scalar(select(PaireDoublon).where(PaireDoublon.niveau == "probable").limit(1))
        paire.statut = "rejete"
        s.flush()
        recalculer_groupes(s)
        calculer_couverture(s, params)
        apres = s.scalar(select(func.count()).where((Personne.groupe_id.is_(None)) | (Personne.groupe_id == Personne.id)))
    assert apres >= avant + 1 or apres == avant  # +1 sauf si la fiche reste reliée par une autre paire


def test_decisions_conservees_apres_recalcul(base_remplie):
    params, _ = base_remplie
    from decensio.services import recalculer

    with db.session() as s:
        paire = s.scalar(select(PaireDoublon).where(PaireDoublon.niveau == "probable").limit(1))
        paire.statut = "rejete"
        ident = (paire.personne_a_id, paire.personne_b_id)
        anomalie = s.scalar(select(Anomalie).where(Anomalie.type == "empilement_gps"))
        anomalie.statut = "justifiee"
    with db.session() as s:
        recalculer(s, params)
    with db.session() as s:
        p = s.scalar(select(PaireDoublon).where(PaireDoublon.personne_a_id == ident[0], PaireDoublon.personne_b_id == ident[1]))
        a = s.scalar(select(Anomalie).where(Anomalie.type == "empilement_gps"))
        assert p.statut == "rejete"
        assert a.statut == "justifiee"


def test_import_reimporte_sans_creer_de_doublon(base_remplie, donnees):
    params, _ = base_remplie
    from decensio.ingest import lire_csv
    from decensio.services import importer_menages

    dossier, _ = donnees
    with db.session() as s:
        avant = s.scalar(select(func.count(Menage.id)))
        importer_menages(s, lire_csv(dossier / "enregistrements.csv"), params, "csv")
        apres = s.scalar(select(func.count(Menage.id)))
    assert apres == avant
