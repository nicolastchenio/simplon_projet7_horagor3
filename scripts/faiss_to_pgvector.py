"""
scripts/faiss_to_pgvector.py
Transfert rapide : vecteurs FAISS existants → colonne pgvector Supabase.
ZERO appel Ollama — on copie juste ce qui est déjà dans faiss.bin.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import faiss
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.rag_tool import _get_db_connection

FAISS_INDEX_PATH = PROJECT_ROOT / "data" / "faiss_index" / "horror_index.faiss"
FAISS_META_PATH  = PROJECT_ROOT / "data" / "faiss_index" / "metadata.pkl"
BATCH_SIZE = 200


def main() -> None:
    logger.info("Chargement de l'index FAISS…")
    index = faiss.read_index(str(FAISS_INDEX_PATH))
    nvec = index.ntotal
    dim = index.d
    logger.info(f"Index chargé : {nvec} vecteurs (dim={dim})")

    logger.info("Chargement des métadonnées…")
    with open(FAISS_META_PATH, "rb") as fh:
        metas: list[dict] = pickle.load(fh)

    if len(metas) != nvec:
        logger.warning(
            f"Désalignement détecté : {nvec} vecteurs vs {len(metas)} métadonnées."
        )

    if not metas or "id_film" not in metas[0]:
        logger.error("Clé 'id_film' absente des métadonnées. Arrêt.")
        return

    # Extraction brute des vecteurs (marche car l'index est de type Flat)
    logger.info("Extraction des vecteurs depuis l'index…")
    all_vectors = index.reconstruct_n(0, nvec)  # ndarray (nvec, dim)

    conn = _get_db_connection()
    cur = conn.cursor()

    ids_batch = []
    vecs_batch = []
    injected = 0

    for i in range(nvec):
        vec = all_vectors[i].tolist()
        id_film = metas[i]["id_film"]

        vecs_batch.append(vec)
        ids_batch.append(id_film)

        if len(ids_batch) >= BATCH_SIZE:
            _flush(cur, vecs_batch, ids_batch)
            injected += len(ids_batch)
            logger.info(f"… {injected}/{nvec} vecteurs transférés")
            vecs_batch.clear()
            ids_batch.clear()

    if ids_batch:
        _flush(cur, vecs_batch, ids_batch)
        injected += len(ids_batch)

    conn.commit()

    # Vérification
    cur.execute("SELECT COUNT(*) FROM film WHERE embedding IS NOT NULL")
    count_in_pg = cur.fetchone()[0]

    cur.close()
    conn.close()

    logger.success(
        f"Terminé : {injected} vecteurs transférés. "
        f"Films avec embedding pgvector : {count_in_pg}/{nvec}."
    )


def _flush(cur, vectors: list[list[float]], ids: list[int]) -> None:
    """UPDATE batché. Les vecteurs sont castés ::vector."""
    for vec, id_f in zip(vectors, ids):
        cur.execute(
            "UPDATE film SET embedding = %s::vector WHERE id_film = %s",
            (vec, id_f),
        )


if __name__ == "__main__":
    main()