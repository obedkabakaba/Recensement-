from decensio.noms import cle_phonetique, cles_phonetiques, elements_du_nom, empreinte, empreinte_nin, jetons_nom


def test_variantes_orthographiques_meme_cle():
    groupes = [
        ["Tshibangu", "Tchibangu", "Chibangu"],
        ["Ilunga", "Ilounga"],
        ["Kasongo", "Kassongo"],
        ["Kalonji", "Kalondji"],
        ["Mwamba", "Mouamba"],
        ["Kabasele", "Kabasélé", "Kabaselle"],
        ["Mbuyi", "Mbuyie"],
        ["Nkulu", "Nkoulou"],
        ["Lukusa", "Loukoussa"],
        ["Jacques", "Jacque"],
    ]
    for groupe in groupes:
        assert len({cle_phonetique(n) for n in groupe}) == 1, groupe


def test_noms_differents_cles_differentes():
    assert cle_phonetique("Kabasele") != cle_phonetique("Kabamba")
    assert cle_phonetique("Mbala") != cle_phonetique("Mbuyi")


def test_elements_du_nom_ignore_mots_vides_et_ordre():
    assert elements_du_nom("Kabila wa Kabange", None, "Joseph") == ["kabila", "kabange", "joseph"]
    assert cles_phonetiques("Mukendi", "Ilunga", "Grâce") == cles_phonetiques("Ilounga", "Grace", "Moukendi")


def test_empreintes_stables_et_secretes():
    assert empreinte("kabasele", "s1") == empreinte("kabasele", "s1")
    assert empreinte("kabasele", "s1") != empreinte("kabasele", "s2")
    assert "kabasele" not in " ".join(jetons_nom("s1", "Kabasele"))


def test_empreinte_nin_normalise_le_format():
    assert empreinte_nin("CD-123 456", "s") == empreinte_nin("cd123456", "s")
    assert empreinte_nin("", "s") is None
