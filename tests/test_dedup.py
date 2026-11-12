from datetime import date

from decensio.dedup import Fiche, generer_candidats, score_paire


def fiche(id, cles, sexe="M", annee=1990, dn=None, nin=None, lien="chef", lat=-4.40, lon=15.37, menage=None):
    return Fiche(id=id, menage_id=menage or id, cles=sorted(cles), jetons=set(cles), sexe=sexe, annee=annee,
                 date_naissance=dn, nin=nin, lien=lien, lat=lat, lon=lon, zone_id=1)


def test_meme_personne_orthographes_differentes():
    a = fiche(1, ["cibangu", "jean", "mukendi"], dn=date(1990, 5, 2))
    b = fiche(2, ["cibangu", "jean", "mukendi"], dn=date(1990, 5, 2), lat=-4.4001)
    assert score_paire(a, b).score >= 0.95


def test_prenom_different_pas_un_doublon():
    a = fiche(1, ["cibangu", "jean", "mukendi"])
    b = fiche(2, ["cibangu", "patrik", "mukendi"])
    assert score_paire(a, b).score < 0.7


def test_sexe_different_fait_chuter_le_score():
    a = fiche(1, ["kabasel", "mari"], sexe="F")
    b = fiche(2, ["kabasel", "mari"], sexe="M")
    assert score_paire(a, b).score < 0.5


def test_meme_nin_score_maximal():
    a = fiche(1, ["kabasel"], nin="x")
    b = fiche(2, ["autre"], nin="x", sexe="F", annee=1950)
    assert score_paire(a, b).score == 1.0


def test_homonyme_frequent_loin_reste_a_verifier():
    a = fiche(1, ["ilunga", "jean"], annee=1990)
    b = fiche(2, ["ilunga", "jean"], annee=1990, lat=-4.30, lon=15.25)
    assert score_paire(a, b, frequence_nom=50).score < 0.85


def test_jumeaux_meme_menage_differente_naissance():
    a = fiche(1, ["kanku", "glodi"], dn=date(2015, 1, 1), menage=9, lien="enfant")
    b = fiche(2, ["kanku", "glodi"], dn=date(2019, 3, 3), menage=9, lien="enfant")
    assert score_paire(a, b).score < 0.7


def test_candidats_par_paires_de_noms():
    fiches = [
        fiche(1, ["cibangu", "jean", "mukendi"]),
        fiche(2, ["cibangu", "jean"]),
        fiche(3, ["kasongo", "pier"]),
        fiche(4, ["cibangu"]),  # un seul élément : comparé à ceux qui le partagent
    ]
    paires = generer_candidats(fiches)
    assert (1, 2) in paires
    assert (1, 4) in paires and (2, 4) in paires
    assert not any(3 in p for p in paires)
