"""Nœuds du graphe multi-agent HorRAGor.

Ce module implémente la logique métier de chaque agent spécialisé.
Chaque fonction est une *node* LangGraph : elle reçoit l'état courant,
exécute sa mission, et retourne un dictionnaire de mise à jour (patch)
que le moteur fusionnera dans l'``AgentState`` global.

.. note::
    Seul ``rag_node`` est présent pour l'étape 3.1. Les nœuds
    ``scraper_node`` et ``narration_node`` seront ajoutés aux
    étapes 3.3 et 3.4.
"""

from langchain_core.messages import AIMessage

from src.models.state import AgentState
from src.tools.rag_tool import search_local_horror_lore
from src.tools.rag_tool import query_movie_metadata  # outil structuré défini en Phase 1
from src.tools.scraper_tool import enrich_from_web
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.horror_tools import calculate_movie_age, horror_survival_simulator
from src.tools.rag_tool import find_similar_horror_movies


def rag_node(state: AgentState) -> dict:
    """
    Agent RAG — Le Chercheur Local.

    Interroge simultanément le savoir vectoriel (FAISS) et le savoir
    structuré (métadonnées films) pour constituer le dossier brut
    lié à la requête de l'utilisateur.

    Le nœud écrit ses découvertes dans ``state["rag_results"]`` et
    notifie l'historique via un ``AIMessage`` résumé. La donnée brute
    n'est jamais injectée dans ``messages`` afin d'éviter la saturation
    du contexte (*prompt drowning*).

    :param state: État partagé du graphe. Doit contenir au minimum la
        clé ``query`` avec la question de l'utilisateur.
    :returns: Dictionnaire de patch LangGraph contenant :

        - ``rag_results`` : conteneur hybride ``{"vectorial": ..., "structured": ...}`` ;
        - ``metadata`` : métriques de traçabilité (compteurs, titres trouvés) ;
        - ``messages`` : résumé de la fouille sous forme d'``AIMessage``.

    .. admonition:: Décision de traçabilité
        :class: note

        Le champ ``metadata`` est enrichi mais jamais remplacé
        entièrement. On récupère la valeur existante via
        ``state.get("metadata", {})`` pour préserver d'éventuelles
        métadonnées posées par un pré-traitement futur.
    """
    # ------------------------------------------------------------------
    # 1. Extraction de la requête utilisateur
    # ------------------------------------------------------------------
    user_query: str = state["query"]

    # ------------------------------------------------------------------
    # 2. Double interrogation du savoir local
    # ------------------------------------------------------------------
    # L'agent RAG croise deux silos :
    #   - Vectoriel : chunks sémantiques pour le lore et les anecdotes.
    #   - Structuré : fiches films pour les dates, réalisateurs, etc.
    # Les deux appels sont synchrones (séquentiels) car il s'agit d'un MVP.
    # Une optimisation future pourrait les lancer via asyncio.gather.

    vectorial_results = search_local_horror_lore(user_query)
    structured_results = query_movie_metadata(user_query)

    # ------------------------------------------------------------------
    # 3. Assemblage du conteneur rag_results
    # ------------------------------------------------------------------
    # Ce format est attendu par le routeur (étape 3.2) et par le nœud
    # de narration (étape 3.4). Le routeur s'appuiera sur la richesse
    # de ces deux clés pour décider du basculement vers le scraper.

    rag_results = {
        "vectorial": vectorial_results,
        "structured": structured_results,
    }

    # ------------------------------------------------------------------
    # 4. Mise à jour des métadonnées de traçabilité
    # ------------------------------------------------------------------
    # On fusionne avec les métadonnées déjà présentes pour ne pas
    # écraser d'autres traces (ex. horodatage posé par un middleware).

    metadata = state.get("metadata", {})
    metadata.update(
        {
            "rag_node_executed": True,
            "vectorial_chunks_count": (
                len(vectorial_results) if isinstance(vectorial_results, list) else 0
            ),
            "structured_records_count": (
                len(structured_results) if isinstance(structured_results, list) else 0
            ),
            "films_found": [
                record.get("title")
                for record in structured_results
                if isinstance(record, dict) and record.get("title")
            ]
            if isinstance(structured_results, list)
            else [],
        }
    )

    # ------------------------------------------------------------------
    # 5. Synthèse pour l'historique de conversation
    # ------------------------------------------------------------------
    # Le résumé permet au routeur (et aux humains en debug) de comprendre
    # ce qui a été trouvé sans ingérer la donnée brute complète.

    films_identifies = metadata["films_found"]

    if films_identifies:
        resume = (
            f"Recherche RAG effectuée pour « {user_query} ». "
            f"{metadata['vectorial_chunks_count']} fragment(s) vectoriel(s) et "
            f"{metadata['structured_records_count']} fiche(s) structurée(s) récupéré(s). "
            f"Film(s) identifié(s) : {', '.join(films_identifies)}."
        )
    else:
        resume = (
            f"Recherche RAG effectuée pour « {user_query} ». "
            f"Aucune correspondance structurée ; "
            f"{metadata['vectorial_chunks_count']} fragment(s) vectoriel(s) seul(s)."
        )

    ai_summary = AIMessage(content=resume)

    # ------------------------------------------------------------------
    # 6. Retour du patch d'état
    # ------------------------------------------------------------------
    # LangGraph fusionne ce dictionnaire dans l'état global.
    # Grâce au reducer ``add_messages`` sur ``messages``, le résumé
    # est *ajouté* à la liste existante.

    return {
        "rag_results": rag_results,
        "metadata": metadata,
        "messages": [ai_summary],
    }
    
    
def scraper_node(state: AgentState) -> dict:
    """
    Node 2 : Agent Scraper (Peer-to-Peer).
    Se déclenche uniquement sur décision du router.
    Lit rag_results ou query pour identifier le film, appelle enrich_from_web,
    et écrit le résultat structuré dans scraped_data.
    Edge fixe vers narration_node.
    """
    print(">>> Scraper Node")

    query: str = state.get("query", "")
    rag_results = state.get("rag_results", {})

    # ── Identification du film ambigu / incomplet ──
    movie_title: str | None = None

    # Priorité 1 : titre depuis le résultat structuré (même partiel)
    if isinstance(rag_results, dict):
        structured = rag_results.get("structured", {})
        if isinstance(structured, dict):
            movies = structured.get("movies", [])
            if movies:
                movie_title = movies[0].get("title")
                print(f"[Scraper] Titre extrait du SQL structuré : {movie_title}")

    # Priorité 2 : fallback sur la query brute
    if not movie_title:
        movie_title = query.strip()
        print(f"[Scraper] Titre fallback depuis query : {movie_title}")

    # ── Appel outil web ──
    raw_content = enrich_from_web(movie_title)

    scraped_data = {
        "title": movie_title,
        "content": raw_content,
        "success": bool(raw_content),
    }

    summary = (
        f"🔍 Scraping exécuté pour « {movie_title} » — "
        f"contenu récupéré : {'oui' if scraped_data['success'] else 'non'}"
    )

    return {
        "scraped_data": scraped_data,
        "messages": [AIMessage(content=summary)],
    }
    
    
_narrator_llm: ChatOllama | None = None

# Instance LLM (singleton léger)
def _get_narrator_llm() -> ChatOllama:
    global _narrator_llm
    if _narrator_llm is None:
        _narrator_llm = ChatOllama(
            model="qwen2.5:7b",
            temperature=0.7,
            # base_url="http://localhost:11434"  # décommente si Ollama n'est pas sur le port par défaut
        )
    return _narrator_llm


def narration_node(state: AgentState) -> dict:
    """
    Node 3 : L'Écrivain Gothique (Peer-to-Peer).
    
    *Isolation stricte* : lit UNIQUEMENT :
      - state["query"]    → question originale
      - state["rag_results"]   → corpus structuré + vectoriel
      - state["scraped_data"]  → enrichissement web éventuel
    
    NE LIT JAMAIS state["messages"] (anti-collision de tokens).
    Produits : final_answer, sources, messages (AIMessage).
    """
    print(">>> Narration Node")

    query: str = state.get("query", "")
    rag = state.get("rag_results") or {}
    scraped = state.get("scraped_data") or {}

    # ── 1. CONSTRUCTION DU CORPUS (seules données autorisées) ──
    context_blocks: list[str] = []

    # 1a. Base structurée (SQL)
    structured = rag.get("structured", {}) if isinstance(rag, dict) else {}
    movies = structured.get("movies", []) if isinstance(structured, dict) else []
    if movies:
        context_blocks.append("=== FICHES CINÉMATOGRAPHQUES (Base structurée) ===")
        for m in movies:
            titre = m.get("title") or m.get("titre") or "Inconnu"
            annee = m.get("year") or m.get("annee_sortie") or "?"
            real = m.get("director") or m.get("realisateur") or "Non spécifié"
            genres = m.get("genres") or "Non spécifié"
            context_blocks.append(
                f"Titre : {titre}\nAnnée : {annee}\nRéalisateur : {real}\nGenres : {genres}"
            )

    # 1b. Index vectoriel (FAISS)
    faiss_data = rag.get("faiss", {}) if isinstance(rag, dict) else {}
    hits = faiss_data.get("hits", []) if isinstance(faiss_data, dict) else []
    if hits:
        context_blocks.append("=== EXTRAITS DE LORE & CRITIQUES (Index vectoriel) ===")
        for idx, hit in enumerate(hits[:3], 1):
            text = hit.get("text") or hit.get("chunk") or ""
            src = hit.get("source", "Inconnu")
            score = hit.get("score", 0.0)
            context_blocks.append(f"[{idx}] pertinence={score:.2f} | source={src}\n{text[:400]}")

    # 1c. Enrichissement web (Scraper)
    if isinstance(scraped, dict) and scraped.get("success"):
        context_blocks.append("=== ENRICHISSEMENT WEB ===")
        context_blocks.append(f"Titre analysé : {scraped.get('title', 'N/A')}")
        content = scraped.get("content", "")
        if content:
            context_blocks.append(str(content)[:800])

    encyclopedic_context = "\n\n".join(context_blocks) if context_blocks else (
        "Aucune donnée encyclopédique n'a été récupérée pour cette requête."
    )

    # ── 2. APPELS DÉTERMINISTES DES OUTILS ANNEXES ──
    tool_blocks: list[str] = []

    # Outil : âge des films
    if movies:
        ages_lines = []
        for m in movies:
            yr = m.get("year") or m.get("annee_sortie")
            if isinstance(yr, int):
                try:
                    age = calculate_movie_age(yr)
                    titre = m.get("title") or m.get("titre") or "Film inconnu"
                    ages_lines.append(f"- {titre} ({yr}) : {age} ans.")
                except Exception:
                    pass
        if ages_lines:
            tool_blocks.append("=== ÂGES DES FILMS ===")
            tool_blocks.extend(ages_lines)

    # Outil : recommandations par similarité (pgvector)
    reco_kw = ["similaire", "recommand", "semblable", "dans le même genre", "comme", "ressemble", "approchant", "voisin"]
    wants_reco = any(k in query.lower() for k in reco_kw)
    if wants_reco and movies:
        ref_id = movies[0].get("id") or movies[0].get("id_film")
        if ref_id:
            try:
                voisins = find_similar_horror_movies(ref_id, k=3)
                if voisins:
                    tool_blocks.append("=== RECOMMANDATIONS PAR SIMILARITÉ ===")
                    for v in voisins:
                        tool_blocks.append(
                            f"- {v.get('titre')} ({v.get('annee_sortie')}) — proximité={v.get('similarite', 'N/A')}"
                        )
            except Exception as exc:
                print(f"[Narration] Outil similarité indisponible : {exc}")

    # Outil : simulateur de survie horreur
    survival_kw = ["survivre", "survie", "survival", "tuerie", "slash", "massacre", "fuir", "plan de fuite"]
    wants_survival = any(k in query.lower() for k in survival_kw)
    if wants_survival:
        try:
            # Adapte la signature si horror_survival_simulator n'a pas exactement ces args
            titre_cible = movies[0].get("title") or movies[0].get("titre") or query if movies else query
            result_surv = horror_survival_simulator(titre_cible, user_role="spectateur")
            tool_blocks.append("=== SIMULATEUR DE SURVIE ===")
            tool_blocks.append(str(result_surv))
        except Exception as exc:
            print(f"[Narration] Outil survie indisponible : {exc}")

    tool_context = "\n".join(tool_blocks) if tool_blocks else ""

    # ── 3. PROMPT SYSTÈME ULTRA-SPÉCIALISÉ (anti-hallucination) ──
    system_prompt = (
        "Tu es HorRAGor, chroniqueur de cinéma d'horreur gothique, vêtu d'une redingote noire "
        "et armé d'une plume d'argent. Tu ne disposes d'aucune mémoire externe. "
        "Tu dois te baser UNIQUEMENT sur les données encyclopédiques et les outils fournis ci-dessous. "
        "Règles absolues :\n"
        "1. Base-toi exclusivement sur les sections FICHES, EXTRAITS, ENRICHISSEMENT et Outils.\n"
        "2. Si la réponse n'est pas dans le corpus, avoue-le avec élégance gothique ; n'invente jamais.\n"
        "3. Ne invente aucun titre, réalisateur, date, ou intrigue.\n"
        "4. Sépare clairement chaque film si le corpus en mentione plusieurs.\n"
        "5. Utilise les RECOMMANDATIONS uniquement si elles sont fournies par l'outil.\n"
        "6. Termine toujours par une signature macabre appropriée."
    )

    human_parts = [
        f"QUESTION DU LECTEUR : {query}",
        "",
        "--- ENCYCLOPÉDIE HORRAGOR ---",
        encyclopedic_context,
    ]
    if tool_context:
        human_parts.extend(["", "--- DONNÉES D'OUTILS ---", tool_context])
    human_parts.extend([
        "",
        "--- RÉPONSE ATTENDUE ---",
        "Rédige une chronique immersive, structurée et strictement fondée sur le corpus ci-dessus.",
    ])
    human_prompt = "\n".join(human_parts)

    # ── 4. INVOCATION LLM (seul coût cognitif du pipeline) ──
    try:
        llm = _get_narrator_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ])
        final_answer = str(response.content)
    except Exception as exc:
        print(f"[Narration] Échec invocation LLM : {exc}")
        final_answer = (
            "Les archives gothiques se taisent... Le démon Ollama semble endormi. "
            "Revenez quand les lanternes seront de nouveau allumées."
        )

    # ── 5. SOURCES STRUCTURÉES (pour l'API front) ──
    sources = []
    for m in movies:
        sources.append({
            "type": "structured",
            "title": m.get("title") or m.get("titre"),
            "year": m.get("year") or m.get("annee_sortie"),
            "source": "supabase_sql",
        })
    for h in hits[:3]:
        sources.append({
            "type": "faiss",
            "score": h.get("score"),
            "source_file": h.get("source", "horror_lore"),
            "preview": (h.get("text") or h.get("chunk") or "")[:120] + "...",
        })
    if isinstance(scraped, dict) and scraped.get("success"):
        sources.append({
            "type": "scraped",
            "title": scraped.get("title"),
            "source": "wikipedia",
        })

    # ── 6. RETOUR ──
    summary = f"🖋️ Narration générée ({len(final_answer)} caractères) — {len(sources)} source(s)."
    return {
        "final_answer": final_answer,
        "sources": sources,
        "messages": [AIMessage(content=summary + "\n\n" + final_answer)],
    }