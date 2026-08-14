"""Outil de récupération web pour enrichir la base de connaissances HorRAGor.

Ce module interroge l'API MediaWiki de Wikipédia FR pour localiser
précisément la section *Synopsis* (ou *Résumé*) d'un film, puis
nettoie le HTML reçu afin de produire un texte brut exploitable
par le LLM.

Traçabilité
-----------
Chaque appel réseau journalise : URL cible, paramètres, statut HTTP,
durée en millisecondes et taille de la réponse. Les échecs réseau
(timeout, erreur de connexion, statut HTTP non-2xx) et les anomalies
de parsing sont explicitement tracés avant retour d'une valeur neutre.
"""

from __future__ import annotations

import re
import time
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

logger.debug(
    f"[Scraper] Configuration : langue='{WIKIPEDIA_LANG}', "
    f"endpoint='{WIKI_API_URL}', timeout={REQUEST_TIMEOUT}s, "
    f"user_agent='{HEADERS['User-Agent']}'"
)

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

    Notes
    -----
    Journalise l'URL complète appelée, le statut HTTP, la durée de la
    requête et le nombre de sections retournées. Les erreurs réseau et
    les erreurs applicatives MediaWiki sont tracées sans lever
    d'exception : la fonction retourne une liste vide pour permettre
    au flux d'enrichissement de dégrader proprement.
    """
    logger.info(f"[Scraper] Entrée _fetch_page_sections : titre='{title}'")

    if not title or not title.strip():
        logger.warning(
            "[Scraper] Titre vide ou blanc fourni à _fetch_page_sections, "
            "abandon de l'appel réseau"
        )
        return []

    params: dict[str, str | int] = {
        "action": "parse",
        "page": title,
        "prop": "sections",
        "redirects": 1,       # suit automatiquement les redirections
        "format": "json",
    }

    url_complete = f"{WIKI_API_URL}?{urllib.parse.urlencode(params)}"
    logger.debug(f"[Scraper] Appel HTTP GET (sections) : {url_complete}")
    logger.debug(f"[Scraper] Paramètres sections : {params}")

    debut = time.perf_counter()
    try:
        resp = requests.get(
            WIKI_API_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.info(
            f"[Scraper] Réponse HTTP (sections) : statut={resp.status_code}, "
            f"durée={duree_ms:.2f} ms, taille={len(resp.content)} octets"
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] TIMEOUT API sections après {duree_ms:.2f} ms "
            f"(limite={REQUEST_TIMEOUT}s) pour « {title} » : {exc}"
        )
        return []
    except requests.HTTPError as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] Statut HTTP invalide (sections) après {duree_ms:.2f} ms "
            f"pour « {title} » : {exc}"
        )
        return []
    except requests.RequestException as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] Échec réseau API sections après {duree_ms:.2f} ms "
            f"pour « {title} » : {type(exc).__name__} — {exc}"
        )
        return []
    except ValueError as exc:
        logger.error(
            f"[Scraper] Réponse JSON invalide (sections) pour « {title} » : {exc}"
        )
        return []

    if "error" in data:
        logger.warning(
            f"[Scraper] API MediaWiki retourne une erreur pour « {title} » : "
            f"code={data['error'].get('code', 'inconnu')}, "
            f"info={data['error'].get('info', 'inconnue')}"
        )
        return []

    sections = data.get("parse", {}).get("sections", [])
    titre_resolu = data.get("parse", {}).get("title", title)
    if titre_resolu != title:
        logger.info(
            f"[Scraper] Redirection Wikipédia suivie : "
            f"« {title} » → « {titre_resolu} »"
        )

    if not sections:
        logger.warning(
            f"[Scraper] Aucune section retournée par l'API pour « {title} » "
            f"(article sans sommaire ou page inexistante)"
        )
    else:
        logger.info(
            f"[Scraper] Sections récupérées : nb={len(sections)} "
            f"pour « {titre_resolu} »"
        )
        logger.debug(
            "[Scraper] Titres des sections : "
            f"{[s.get('line') for s in sections]}"
        )

    return sections


def _fetch_section_html(title: str, section_index: str) -> str:
    """Récupère le contenu HTML d'une section précise via l'API.

    Parameters
    ----------
    title :
        Titre de la page.
    section_index :
        Identifiant ``index`` de la section (il s'agit d'une chaîne
        comme ``"2"``, ``"3"``, etc.).

    Returns
    -------
    str
        Fragment HTML brut de la section, ou chaîne vide en cas
        d'échec réseau, de réponse JSON invalide ou d'erreur MediaWiki.

    Notes
    -----
    Journalise l'URL appelée, le statut HTTP, la durée et la taille du
    fragment HTML obtenu, ce qui permet de distinguer un échec réseau
    d'une section réellement vide côté Wikipédia.
    """
    logger.info(
        f"[Scraper] Entrée _fetch_section_html : titre='{title}', "
        f"index_section='{section_index}'"
    )

    params: dict[str, str | int] = {
        "action": "parse",
        "page": title,
        "section": section_index,
        "prop": "text",
        "redirects": 1,
        "format": "json",
    }

    url_complete = f"{WIKI_API_URL}?{urllib.parse.urlencode(params)}"
    logger.debug(f"[Scraper] Appel HTTP GET (texte) : {url_complete}")

    debut = time.perf_counter()
    try:
        resp = requests.get(
            WIKI_API_URL,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.info(
            f"[Scraper] Réponse HTTP (texte) : statut={resp.status_code}, "
            f"durée={duree_ms:.2f} ms, taille={len(resp.content)} octets"
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] TIMEOUT API texte (section {section_index}) après "
            f"{duree_ms:.2f} ms pour « {title} » : {exc}"
        )
        return ""
    except requests.HTTPError as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] Statut HTTP invalide (texte, section {section_index}) "
            f"après {duree_ms:.2f} ms pour « {title} » : {exc}"
        )
        return ""
    except requests.RequestException as exc:
        duree_ms = (time.perf_counter() - debut) * 1000
        logger.error(
            f"[Scraper] Échec réseau API texte (section {section_index}) après "
            f"{duree_ms:.2f} ms pour « {title} » : {type(exc).__name__} — {exc}"
        )
        return ""
    except ValueError as exc:
        logger.error(
            f"[Scraper] Réponse JSON invalide (texte, section {section_index}) "
            f"pour « {title} » : {exc}"
        )
        return ""

    if "error" in data:
        logger.warning(
            f"[Scraper] API MediaWiki retourne une erreur (texte, section "
            f"{section_index}) pour « {title} » : "
            f"code={data['error'].get('code', 'inconnu')}, "
            f"info={data['error'].get('info', 'inconnue')}"
        )
        return ""

    html_fragment = data.get("parse", {}).get("text", {}).get("*", "")

    if not html_fragment:
        logger.warning(
            f"[Scraper] Fragment HTML vide retourné pour la section "
            f"{section_index} de « {title} » (clé 'text' absente ou vide)"
        )
    else:
        logger.info(
            f"[Scraper] Fragment HTML récupéré : {len(html_fragment)} "
            f"caractères (section {section_index} de « {title} »)"
        )

    return html_fragment


def _clean_wiki_html(html_fragment: str) -> str:
    """Nettoie un fragment HTML Wikipédia et retourne le texte brut.

    * Supprime les `<sup>` (numéros de référence comme ``[1]``, ``[2]``).
    * Supprime les liens ``[modifier]`` et espaces superflus.
    * Concatène les paragraphes avec des sauts de ligne.

    Parameters
    ----------
    html_fragment :
        Fragment HTML brut issu de l'API MediaWiki.

    Returns
    -------
    str
        Texte nettoyé, paragraphes séparés par une ligne vide.
        Chaîne vide si le fragment est vide ou ne contient aucun ``<p>``.

    Notes
    -----
    Journalise le taux de compression (HTML entrant vs texte sortant),
    le nombre de balises ``<sup>`` retirées et le nombre de paragraphes
    conservés — indicateurs utiles pour détecter un sélecteur inadapté.
    """
    if not html_fragment:
        logger.warning(
            "[Scraper] _clean_wiki_html reçoit un fragment vide, "
            "nettoyage ignoré"
        )
        return ""

    taille_entree = len(html_fragment)
    logger.debug(
        f"[Scraper] Début nettoyage HTML : {taille_entree} caractères entrants"
    )

    debut = time.perf_counter()
    soup = BeautifulSoup(html_fragment, "html.parser")

    # Retire les notes de bas de page / références numérotées
    sup_tags = soup.find_all("sup")
    for tag in sup_tags:
        tag.decompose()
    logger.debug(
        f"[Scraper] Balises <sup> supprimées : {len(sup_tags)}"
    )

    balises_p = soup.find_all("p")
    logger.debug(f"[Scraper] Balises <p> détectées : {len(balises_p)}")

    if not balises_p:
        logger.warning(
            "[Scraper] Aucune balise <p> trouvée dans le fragment HTML "
            "(structure Wikipédia inattendue ou sélecteur obsolète)"
        )

    paragraphs: list[str] = []
    paragraphes_vides = 0
    for p in balises_p:
        text = p.get_text(separator=" ", strip=True)
        # Supprime d'éventuelles références résiduelles
        text = re.sub(r"\[\d+\]", "", text)
        # Supprime l'espace avant la ponctuation simple
        text = re.sub(r"\s+([.,;:!?)])", r"\1", text)
        # Élimine les espaces multiples
        text = re.sub(r" {2,}", " ", text)
        if text:
            paragraphs.append(text)
        else:
            paragraphes_vides += 1

    resultat = "\n\n".join(paragraphs)
    duree_ms = (time.perf_counter() - debut) * 1000
    taux = (len(resultat) / taille_entree * 100) if taille_entree else 0.0

    logger.info(
        f"[Scraper] Nettoyage HTML terminé : {len(paragraphs)} paragraphe(s) "
        f"conservé(s), {paragraphes_vides} ignoré(s), "
        f"{taille_entree} → {len(resultat)} caractères "
        f"({taux:.1f}% conservés), durée={duree_ms:.2f} ms"
    )

    if not resultat:
        logger.warning(
            "[Scraper] Texte vide après nettoyage alors que le fragment HTML "
            f"faisait {taille_entree} caractères"
        )

    return resultat


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

    Notes
    -----
    Chacune des 4 étapes est tracée avec son résultat intermédiaire et
    la durée totale du pipeline est journalisée en sortie, ce qui permet
    d'identifier précisément l'étape qui échoue lorsqu'aucun synopsis
    n'est retourné.
    """
    logger.info(
        f"[Scraper] === Début extraction synopsis pour « {movie_title} » ==="
    )
    debut_total = time.perf_counter()

    if not movie_title or not movie_title.strip():
        logger.warning(
            "[Scraper] Titre de film vide fourni à "
            "extract_wikipedia_synopsis, abandon"
        )
        return ""

    # 1. Liste des sections
    logger.debug("[Scraper] Étape 1/4 : récupération de la liste des sections")
    sections = _fetch_page_sections(movie_title)
    if not sections:
        logger.warning(
            f"[Scraper] ÉCHEC étape 1/4 — Aucune section trouvée via API pour "
            f"« {movie_title} » (la page n'existe probablement pas sous ce "
            f"nom exact). Durée={(time.perf_counter() - debut_total) * 1000:.2f} ms"
        )
        return ""

    # 2. Recherche de la section pertinente
    logger.debug(
        "[Scraper] Étape 2/4 : recherche de la section synopsis/résumé"
    )
    target_index: str | None = None
    keywords = ("synopsis", "résumé", "intrigue", "histoire")
    logger.debug(f"[Scraper] Mots-clés de section recherchés : {keywords}")

    for sec in sections:
        line = sec.get("line", "").lower()
        anchor = sec.get("anchor", "").lower()
        if any(kw in line or kw in anchor for kw in keywords):
            target_index = sec.get("index")
            logger.info(
                f"[Scraper] Section pertinente trouvée : « {sec.get('line')} » "
                f"(index={target_index}, anchor='{sec.get('anchor')}', "
                f"toclevel={sec.get('toclevel')})"
            )
            break

    if target_index is None:
        logger.warning(
            f"[Scraper] ÉCHEC étape 2/4 — Aucune section "
            f"synopsis/résumé/intrigue/histoire parmi les {len(sections)} "
            f"sections de « {movie_title} ». "
            f"Sections disponibles : {[s.get('line') for s in sections]}"
        )
        return ""

    # 3. Récupération du HTML de la section isolée
    logger.debug(
        f"[Scraper] Étape 3/4 : récupération du HTML de la section "
        f"{target_index}"
    )
    raw_html = _fetch_section_html(movie_title, target_index)
    if not raw_html:
        logger.warning(
            f"[Scraper] ÉCHEC étape 3/4 — Section « {target_index} » vide ou "
            f"inaccessible pour « {movie_title} »"
        )
        return ""

    # 4. Nettoyage
    logger.debug("[Scraper] Étape 4/4 : nettoyage du fragment HTML")
    synopsis = _clean_wiki_html(raw_html)
    if not synopsis:
        logger.warning(
            f"[Scraper] ÉCHEC étape 4/4 — Synopsis vide après nettoyage pour "
            f"« {movie_title} » (fragment HTML de {len(raw_html)} caractères)"
        )
        return ""

    duree_totale_ms = (time.perf_counter() - debut_total) * 1000
    logger.success(
        f"[Scraper] Synopsis extrait pour « {movie_title} » "
        f"({len(synopsis)} caractères, {synopsis.count(chr(10) * 2) + 1} "
        f"paragraphe(s), durée totale={duree_totale_ms:.2f} ms)"
    )
    logger.debug(f"[Scraper] Aperçu synopsis : {synopsis[:200]}...")
    return synopsis


def enrich_from_web(movie_title: str) -> str:
    """Construit un bloc d'enrichissement prêt à être injecté dans le state.

    Appelle :func:`extract_wikipedia_synopsis`, puis encapsule le résultat
    dans des balises de source pour que l'agent sache d'où provient
    l'information.

    Parameters
    ----------
    movie_title :
        Titre du film à enrichir depuis le web.

    Returns
    -------
    str
        Bloc textuel balisé ``[Source : Wikipédia — <titre>]`` ...
        ``[Fin de l'extrait Wikipédia]``, ou chaîne vide si aucun
        synopsis n'a pu être récupéré.

    Notes
    -----
    Journalise explicitement le cas « aucun enrichissement » afin que
    l'absence de source web dans la réponse finale du LLM soit
    traçable dans les logs.
    """
    logger.info(
        f"[Scraper] Entrée enrich_from_web : titre='{movie_title}'"
    )
    debut = time.perf_counter()

    synopsis = extract_wikipedia_synopsis(movie_title)

    if not synopsis:
        logger.warning(
            f"[Scraper] Aucun enrichissement web pour « {movie_title} » — "
            f"le contexte LLM ne contiendra pas de source Wikipédia. "
            f"Durée={(time.perf_counter() - debut) * 1000:.2f} ms"
        )
        return ""

    block = (
        f"[Source : Wikipédia — {movie_title}]\n"
        f"{synopsis}\n"
        f"[Fin de l'extrait Wikipédia]"
    )

    duree_ms = (time.perf_counter() - debut) * 1000
    logger.success(
        f"[Scraper] Enrichissement généré pour « {movie_title} » "
        f"({len(block)} caractères dont {len(synopsis)} de synopsis, "
        f"durée={duree_ms:.2f} ms)"
    )
    return block