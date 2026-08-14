"""
tests/test_horror_tools.py
============================
Tests unitaires des outils annexes (``src/tools/horror_tools.py``) :
``calculate_movie_age`` et ``horror_survival_simulator``.

Fonctions pures — aucun mock nécessaire, sauf le facteur aléatoire de
``horror_survival_simulator``, figé via ``monkeypatch`` pour obtenir des
assertions déterministes.
"""
from __future__ import annotations

import datetime

import pytest

from src.tools.horror_tools import calculate_movie_age, horror_survival_simulator


# ═══════════════════════════════════════════════════════════════
# calculate_movie_age
# ═══════════════════════════════════════════════════════════════

class TestCalculateMovieAge:
    def test_age_correct_pour_un_film_passe(self):
        annee_actuelle = datetime.date.today().year
        assert calculate_movie_age(annee_actuelle - 10) == 10

    def test_age_zero_pour_l_annee_courante(self):
        annee_actuelle = datetime.date.today().year
        assert calculate_movie_age(annee_actuelle) == 0

    def test_age_negatif_pour_un_film_futur(self):
        annee_actuelle = datetime.date.today().year
        assert calculate_movie_age(annee_actuelle + 5) == -5

    @pytest.mark.parametrize("valeur_invalide", ["1999", 1999.5, None, [1999]])
    def test_type_invalide_leve_typeerror(self, valeur_invalide):
        with pytest.raises(TypeError):
            calculate_movie_age(valeur_invalide)


# ═══════════════════════════════════════════════════════════════
# horror_survival_simulator
# ═══════════════════════════════════════════════════════════════

def _mock_random(monkeypatch: pytest.MonkeyPatch, valeur: int) -> None:
    """Fige le facteur aléatoire du simulateur à une valeur fixe."""
    monkeypatch.setattr(
        "src.tools.horror_tools.random.randint", lambda a, b: valeur
    )


class TestHorrorSurvivalSimulator:
    @pytest.mark.parametrize(
        "synopsis, contexte",
        [(123, "un texte"), ("un texte", 123), (None, None)],
    )
    def test_type_invalide_leve_typeerror(self, synopsis, contexte):
        with pytest.raises(TypeError):
            horror_survival_simulator(synopsis, contexte)

    def test_score_de_base_sans_mots_cles(self, monkeypatch):
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator(
            "Une simple comédie romantique", "rien de spécial"
        )
        assert "Chances de survie : 50 %" in result

    def test_mots_de_danger_diminuent_le_score(self, monkeypatch):
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator(
            "Un zombie attaque le village", "rien de spécial"
        )
        # 1 mot de danger ("zombie") : 50 - 5 = 45
        assert "Chances de survie : 45 %" in result

    def test_mots_bonus_augmentent_le_score(self, monkeypatch):
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator(
            "Une simple comédie romantique", "j'ai un fusil et je suis fort"
        )
        # 2 mots bonus distincts ("fusil", "fort") : 50 + 8*2 = 66
        assert "Chances de survie : 66 %" in result

    def test_mots_malus_diminuent_le_score(self, monkeypatch):
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator(
            "Une simple comédie romantique", "je suis faible et j'ai peur"
        )
        # 2 mots malus distincts ("faible", "peur") : 50 - 10*2 = 30
        assert "Chances de survie : 30 %" in result

    def test_score_borne_a_100_maximum(self, monkeypatch):
        _mock_random(monkeypatch, 10)
        # 6 mots bonus DISTINCTS : str.count() est non-chevauchant, répéter
        # le même mot plusieurs fois de suite le sous-compterait.
        contexte = "fusil fort courage rapide rusé calme"
        result = horror_survival_simulator("Une comédie", contexte)
        assert "Chances de survie : 100 %" in result

    def test_score_borne_a_0_minimum(self, monkeypatch):
        _mock_random(monkeypatch, -10)
        # 10 mots de danger distincts (10*5=50) + random=-10 : score de base
        # 50 - 50 - 10 = -10, largement sous 0 pour absorber toute marge.
        synopsis = "zombie fantôme démon possession masque hache couteau sang maudit mort"
        result = horror_survival_simulator(synopsis, "rien de spécial")
        assert "Chances de survie : 0 %" in result

    @pytest.mark.parametrize(
        "contexte, extrait_attendu",
        [
            ("fusil fort courage rapide rusé", "protagoniste ultime"),        # 50+40=90
            ("fusil fort", "chances honnêtes"),                                # 50+16=66
            ("rien", "survie est possible"),                                   # 50
            ("faible peur", "premier rang du cimetière"),                      # 50-20=30
            ("faible peur seul naïf", "RIP"),                                  # 50-40=10
        ],
    )
    def test_commentaire_narratif_selon_le_palier(
        self, monkeypatch, contexte, extrait_attendu
    ):
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator("Une comédie", contexte)
        assert extrait_attendu in result

    def test_mot_colle_a_la_ponctuation_non_detecte(self, monkeypatch):
        """Documente une limitation connue de ``_compter_occurrences_mots`` :
        chaque mot-clé est entouré d'espaces stricts, donc un mot directement
        suivi d'une ponctuation (ex. ``"zombie."``) n'est pas détecté comme
        danger — le score reste au niveau de base (50) au lieu de 45."""
        _mock_random(monkeypatch, 0)
        result = horror_survival_simulator("Attention au zombie.", "rien de spécial")
        assert "Chances de survie : 50 %" in result
