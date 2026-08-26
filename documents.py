"""Loads the six policy/contract/product PDFs, splits them into small chunks, and
answers similarity-search queries using sentence-transformers (local embedding model).

Kept intentionally simple: an in-memory list of (text, metadata, embedding) records
and numpy cosine similarity. At this scale -- six short documents, a few dozen chunks
-- a real vector database would be pure overhead.
"""
import re
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

DATA_DIR = Path(__file__).parent / "data"
EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")

DOCUMENT_METADATA = {
    "01_Support_Policy_v3_CURRENT.pdf": {
        "status": "CURRENT", "kind": "support policy"},
    "02_Support_Policy_v2_DEPRECATED.pdf": {
        "status": "DEPRECATED - historical reference only, do not use as current policy",
        "kind": "support policy"},
    "03_Cancellation_and_Service_Credit_SOP_v4.pdf": {
        "status": "CURRENT", "kind": "SOP"},
    "04_Product_Operations_Guide_and_Known_Issues.pdf": {
        "status": "CURRENT", "kind": "product operations guide"},
    "05_Northstar_Logistics_Enterprise_Agreement.pdf": {
        "status": "ACTIVE signed agreement (Northstar Logistics, ACCT-001)",
        "kind": "customer agreement"},
    "06_LumenWorks_Service_Agreement.pdf": {
        "status": "ACTIVE signed agreement (LumenWorks, ACCT-002)",
        "kind": "customer agreement"},
}


def _extract_chunks(pdf_path: Path, min_len: int = 150):
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks, current = [], ""
    for para in paragraphs:
        current = f"{current}\n{para}".strip() if current else para
        if len(current) >= min_len:
            chunks.append(current)
            current = ""
    if current:
        if chunks:
            chunks[-1] += "\n" + current
        else:
            chunks.append(current)
    return chunks


def build_index():
    """Reads every PDF in data/, chunks it, and embeds each chunk. Returns a list of
    dicts: {text, source_file, status, kind, embedding}. Call once per app process."""
    records = []
    for pdf_path in sorted(DATA_DIR.glob("*.pdf")):
        meta = DOCUMENT_METADATA.get(pdf_path.name, {"status": "unknown", "kind": "document"})
        for chunk in _extract_chunks(pdf_path):
            records.append({"text": chunk, "source_file": pdf_path.name, **meta})

    texts = [r["text"] for r in records]
    embeddings = EMBED_MODEL.encode(texts, convert_to_numpy=True)
    for record, embedding in zip(records, embeddings):
        record["embedding"] = embedding
    return records


def search(index, query: str, top_k: int = 4):
    query_vec = EMBED_MODEL.encode(query, convert_to_numpy=True)

    scored = []
    for record in index:
        vec = record["embedding"]
        similarity = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-9))
        scored.append((similarity, record))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        {"source_file": r["source_file"], "status": r["status"], "kind": r["kind"],
         "text": r["text"], "relevance": round(sim, 3)}
        for sim, r in scored[:top_k]
    ]
