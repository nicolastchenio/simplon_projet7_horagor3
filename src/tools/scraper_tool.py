"""Outil de récupération web pour enrichir la base de connaissances HorRAGor.

Ce module interroge l'API MediaWiki de Wikipédia FR pour localiser
précisément la section *Synopsis* (ou *Résumé*) d'un film, puis
nettoie le HTML reçu afin de produire un texte brut exploitable
par le LLM.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Final

import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.config import REQUEST_TIMEOUT, WIKIPEDIA_LANG

# ── Constantes locales (non centralisables car métier fixe) ─────────────
HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "HorRAGorBot/0.1 (Projet Simplon; contact@horragor.local)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}
WIKI_API_URL: Final[str] = f"https://{WIKIPEDIA_LANG}.wikipedia.org/w/api.php"
"""URL de l'API MediaWiki, construite dynamiquement depuis la langue
configurée dans ``src.config`` (défaut : fr)."""


# ── Fonctions internes (API MediaWiki) ─────────────────────────────────

def _fetch_page_sections(title: str) -> list[dict]:
    """Récupère la liste des sections d'un article Wikipédia via l'API.

    Parameters
    ----------
    title :
        Titre de la page, ex: ``"Conjuring : Les Dossiers Warren"``.

    Returns
    -------
    list[dict]
        Liste des sections. Chaque dict contient ``index``, ``line``,
        ``anchor``, ``toclevel``, etc. Liste vide si la page n'existe pas.
    """
    params: dict[str, str | int] = {
        "action": "parse",
        "page": title,
        "prop": "sections",
        "redirects": 1,       # suit automatiquement les redirections
        "format": "json",
    }

    logger.debug(f"API Wikipédia (sections) : {title}")
    try:
        resp = requests.get(
            WIKI_API_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"Échec API sections pour « {title} » : {exc}")
        return []
    except ValueError as exc:
        logger.warning(f"Réponse JSON invalide pour « {title} » : {exc}")
        return []

    if "error" in data:
        logger.info(
            f"API retourne une erreur pour « {title} » : "
            f"{data['error'].get('info', 'inconnue')}"
        )
        return []

    return data.get("parse", {}).get("sections", [])


def _fetch_section_html(title: str, section_index: str) -> str:
    """Récupère le contenu HTML d'une section précise via l'API.

    Parameters
    ----------
    title :
        Titre de la page.
    section_index :
        Identifiant ``index`` de la section (il s'agit d'une chaîne
        comme ``"2"``, ``"3"``, etc.).
    """
    params: dict[str, str | int] = {
        "action": "parse",
        "page": title,
        "section": section_index,
        "prop": "text",
        "redirects": 1,
        "format": "json",
    }

    try:
        resp = requests.get(
            WIKI_API_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            f"Échec API texte (section {section_index}) pour « {title} » : {exc}"
        )
        return ""

    if "error" in data:
        return ""

    return data.get("parse", {}).get("text", {}).get("*", "")


def _clean_wiki_html(html_fragment: str) -> str:
    """Nettoie un fragment HTML Wikipédia et retourne le texte brut.

    * Supprime les `<sup>` (numéros de référence comme ``[1]``, ``[2]``).
    * Supprime les liens ``[modifier]`` et espaces superflus.
    * Concatène les paragraphes avec des sauts de ligne.
    """
    if not html_fragment:
        return ""

    soup = BeautifulSoup(html_fragment, "html.parser")

    # Retire les notes de bas de page / références numérotées
    for tag in soup.find_all("sup"):
        tag.decompose()

    paragraphs: list[str] = []
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        # Supprime d'éventuelles références résiduelles
        text = re.sub(r"\[\d+\]", "", text)
        # Supprime l'espace avant la ponctuation simple
        text = re.sub(r"\s+([.,;:!?)])", r"\1", text)
        # Élimine les espaces multiples
        text = re.sub(r" {2,}", " ", text)
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


# ── Fonction principale (avec fallback HTML si l'API est bloquée) ──────

def extract_wikipedia_synopsis(movie_title: str) -> str:
    """Extrait le synopsis d'un film depuis Wikipédia FR.

    Stratégie :
    1. Interroger l'API pour lister les sections.
    2. Identifier la section dont le titre contient *Synopsis*,
       *Résumé* ou *Intrigue*.
    3. Demander à l'API le HTML **isolé** de cette section seule.
    4. Parser et nettoyer ce fragment HTML.

    Parameters
    ----------
    movie_title :
        Titre du film, tel qu'il peut être tapé par l'utilisateur.

    Returns
    -------
    str
        Texte brut du synopsis, ou chaîne vide si introuvable.
    """
    # 1. Liste des sections
    sections = _fetch_page_sections(movie_title)
    if not sections:
        logger.info(
            f"Aucune section trouvée via API pour « {movie_title} » "
            f"(la page n'existe probablement pas sous ce nom exact)"
        )
        return ""

    # 2. Recherche de la section pertinente
    target_index: str | None = None
    keywords = ("synopsis", "résumé", "intrigue", "histoire")

    for sec in sections:
        line = sec.get("line", "").lower()
        anchor = sec.get("anchor", "").lower()
        if any(kw in line or kw in anchor for kw in keywords):
            target_index = sec.get("index")
            logger.debug(
                f"Section trouvée : « {sec.get('line')} » (index={target_index})"
            )
            break

    if target_index is None:
        logger.info(
            f"Aucune section synopsis/résumé pour « {movie_title} »"
        )
        return ""

    # 3. Récupération du HTML de la section isolée
    raw_html = _fetch_section_html(movie_title, target_index)
    if not raw_html:
        logger.info(
            f"Section « {target_index} » vide ou inaccessible pour « {movie_title} »"
        )
        return ""

    # 4. Nettoyage
    synopsis = _clean_wiki_html(raw_html)
    if not synopsis:
        logger.info(f"Synopsis vide après nettoyage pour « {movie_title} »")
        return ""

    logger.info(
        f"Synopsis extrait pour « {movie_title} » ({len(synopsis)} caractères)"
    )
    return synopsis


def enrich_from_web(movie_title: str) -> str:
    """Construit un bloc d'enrichissement prêt à être injecté dans le state.

    Appelle :func:`extract_wikipedia_synopsis`, puis encapsule le résultat
    dans des balises de source pour que l'agent sache d'où provient
    l'information.
    """
    synopsis = extract_wikipedia_synopsis(movie_title)

    if not synopsis:
        logger.info(f"Aucun enrichissement web pour « {movie_title} »")
        return ""

    block = (
        f"[Source : Wikipédia — {movie_title}]\n"
        f"{synopsis}\n"
        f"[Fin de l'extrait Wikipédia]"
    )

    logger.info(
        f"Enrichissement généré pour « {movie_title} » "
        f"({len(block)} caractères)"
    )
    return block