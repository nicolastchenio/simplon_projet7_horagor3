"""
Outils utilitaires horreur pour le projet Horragor.

Ce module regroupe les fonctions pures utilisées par l'agent de narration
afin d'enrichir l'expérience utilisateur sans accéder à la base de données
ni à des services externes.
"""

import datetime
import random
from typing import Final


# ----------------------------------------------------------------------------
# Constantes de simulation
# ----------------------------------------------------------------------------
# Liste des mots-clés représentant un danger élevé dans un synopsis.
_MOTS_DANGER: Final[list[str]] = [
    "zombie", "zombies", "fantôme", "fantomes", "démon", "demon",
    "possession", "masque", "hache", "couteau", "sang", "maudit",
    "maudite", "mort", "meurtre", "tueur", "tueuse", "cauchemar",
    "mutilation", "extraterrestre", "monstre", "créature", "creature",
    "virus", "apocalypse", "malédiction", "malediction", "épée", "epee",
    "sorcière", "sorciere", "cimetière", "cimetiere", "hanté", "hante",
]

# Liste des atouts utilisateur qui augmentent les chances de survie.
_MOTS_BONUS: Final[list[str]] = [
    "arme", "fusil", "pistolet", "couteau", "batte", "marteau",
    "courage", "brave", "fort", "musclé", "muscle", "sportif", "militaire",
    "police", "médecin", "docteur", "intelligent", "rusé", "ruse",
    "stratège", "strategie", "calme", "prudent", "préparé", "prepare",
    "survivaliste", "course", "rapide",
]

# Liste des handicaps utilisateur qui diminuent les chances de survie.
_MOTS_MALUS: Final[list[str]] = [
    "phobie", "peur", "timide", "faible", "maladroit", "blessé", "blesse",
    "myope", "angoissé", "angoisse", "parano", "naïf", "naif", "seul",
    "somnambule", "insouciant", "téméraire",
]


def calculate_movie_age(year: int) -> int:
    """
    Calcule l'âge d'un film par rapport à l'année civile actuelle.

    Args:
        year: L'année de sortie du film.

    Returns:
        L'âge du film en nombre d'années. Si l'année fournie est
        supérieure à l'année actuelle, la valeur retournée est négative
        (film 'futur').

    Raises:
        TypeError: Si le paramètre ``year`` n'est pas un entier.
    """
    # Vérification du type pour garantir la robustesse de l'outil.
    if not isinstance(year, int):
        raise TypeError("Le paramètre 'year' doit être un entier.")

    # Récupération de l'année actuelle via le module datetime.
    annee_actuelle = datetime.date.today().year

    # L'âge correspond simplement à la différence entre les deux années.
    return annee_actuelle - year


def _compter_occurrences_mots(texte: str, mots: list[str]) -> int:
    """
    Compte le nombre d'occurrences de mots entiers dans un texte.

    Cette fonction interne ajoute des espaces en début et fin de chaîne
    pour simuler des frontières de mots sans utiliser d'expressions
    régulières complexes (gestion des accents).

    Args:
        texte: Le texte dans lequel effectuer la recherche.
        mots: La liste de mots à rechercher.

    Returns:
        Le nombre total d'occurrences trouvées.
    """
    # Normalisation en minuscules pour rendre la recherche insensible à la casse.
    texte_normalise = f" {texte.lower()} "
    total = 0

    # Itération sur chaque mot-clé pour compter ses présences.
    for mot in mots:
        mot_normalise = f" {mot.lower()} "
        total += texte_normalise.count(mot_normalise)

    return total


def horror_survival_simulator(synopsis: str, user_context: str) -> str:
    """
    Simule de manière ludique les chances de survie dans un film d'horreur.

    L'algorithme attribue un score de base, applique des malus liés au
    danger présent dans le synopsis, puis ajuste le résultat selon les
    atouts et handicaps mentionnés dans le contexte utilisateur. Un
    facteur aléatoire final introduit le chaos propre au genre horreur.

    Args:
        synopsis: Le résumé ou le scénario du film.
        user_context: Le profil de l'utilisateur (compétences, équipement,
            phobies, etc.).

    Returns:
        Une chaîne de caractères formatée contenant le pourcentage de
        survie estimé ainsi qu'un commentaire narratif à l'ambiance
        horreur.

    Raises:
        TypeError: Si l'un des paramètres n'est pas une chaîne de caractères.
    """
    # Validation des types d'entrée.
    if not isinstance(synopsis, str) or not isinstance(user_context, str):
        raise TypeError(
            "Les paramètres 'synopsis' et 'user_context' doivent être des chaînes de caractères."
        )

    # ------------------------------------------------------------------------
    # Étape 1 : Score de base
    # ------------------------------------------------------------------------
    # Chaque victime potentielle commence avec une chance moyenne.
    score = 50

    # ------------------------------------------------------------------------
    # Étape 2 : Analyse du danger dans le synopsis
    # ------------------------------------------------------------------------
    # Plus le synopsis contient de mots terrifiants, plus le malus est élevé.
    compteur_danger = _compter_occurrences_mots(synopsis, _MOTS_DANGER)
    score -= compteur_danger * 5

    # ------------------------------------------------------------------------
    # Étape 3 : Analyse du contexte utilisateur (bonus et malus)
    # ------------------------------------------------------------------------
    compteur_bonus = _compter_occurrences_mots(user_context, _MOTS_BONUS)
    score += compteur_bonus * 8

    compteur_malus = _compter_occurrences_mots(user_context, _MOTS_MALUS)
    score -= compteur_malus * 10

    # ------------------------------------------------------------------------
    # Étape 4 : Facteur aléatoire (le hasard fait partie du slasher)
    # ------------------------------------------------------------------------
    # Un tirage entre -10 et +10 pour représenter l'imprévisibilité du scénario.
    score += random.randint(-10, 10)

    # ------------------------------------------------------------------------
    # Étape 5 : Bornage final
    # ------------------------------------------------------------------------
    # Le pourcentage doit rester entre 0 % (décès assuré) et 100 % (invincible).
    score = max(0, min(100, score))

    # ------------------------------------------------------------------------
    # Étape 6 : Génération du commentaire narratif
    # ------------------------------------------------------------------------
    if score >= 80:
        commentaire = (
            "Tu es le protagoniste ultime : le tueur devrait sérieusement "
            "envisager de changer de quartier."
        )
    elif score >= 60:
        commentaire = (
            "Tu as des chances honnêtes de voir le soleil se lever... "
            "tant que tu ne trébuches pas sur une branche en courant."
        )
    elif score >= 40:
        commentaire = (
            "La survie est possible, mais n'accepte surtout pas l'invitation "
            "à 'dormir une dernière nuit' dans la cabane isolée."
        )
    elif score >= 20:
        commentaire = (
            "Les crédits du générique te préparent déjà une place bien "
            "au chaud... au premier rang du cimetière."
        )
    else:
        commentaire = (
            "Désolé, même le scénariste n'a pas prévu que tu survives "
            "au-delà du premier acte. RIP."
        )

    # ------------------------------------------------------------------------
    # Étape 7 : Formatage de la réponse
    # ------------------------------------------------------------------------
    return f"Chances de survie : {score} % — {commentaire}"