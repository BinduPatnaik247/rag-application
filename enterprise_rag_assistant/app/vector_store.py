import chromadb
from sentence_transformers import SentenceTransformer
from app.config import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL

_client = _collection = _model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model

def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection

def add_chunks(chunks, doc_id, filename, uploaded_by, allowed_roles):
    if not chunks:
        raise ValueError("No readable text was found in this file.")
    embeddings = get_model().encode(chunks, normalize_embeddings=True).tolist()
    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    roles = ",".join(sorted(set(allowed_roles)))
    metadatas = [{
        "doc_id": doc_id, "filename": filename, "uploaded_by": uploaded_by,
        "allowed_roles": roles, "chunk_index": i
    } for i in range(len(chunks))]
    get_collection().upsert(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    return len(chunks)

def search_chunks(question, roles, top_k=5):
    collection = get_collection()
    if collection.count() == 0:
        return []
    embedding = get_model().encode([question], normalize_embeddings=True).tolist()[0]
    result = collection.query(
        query_embeddings=[embedding],
        n_results=min(max(top_k * 5, top_k), max(collection.count(), 1)),
        include=["documents", "metadatas", "distances"]
    )
    allowed = set(roles)
    is_admin = "admin" in allowed
    hits = []
    for doc, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        doc_roles = set((meta.get("allowed_roles") or "").split(","))
        if is_admin or allowed.intersection(doc_roles):
            hits.append({
                "text": doc, "filename": meta.get("filename", "unknown"),
                "doc_id": meta.get("doc_id", ""), "chunk_index": meta.get("chunk_index", -1),
                "distance": float(distance)
            })
        if len(hits) >= top_k:
            break
    return hits

def list_documents():
    collection = get_collection()
    if collection.count() == 0:
        return []
    data = collection.get(include=["metadatas"])
    unique = {}
    for meta in data["metadatas"]:
        unique[meta["doc_id"]] = {
            "doc_id": meta["doc_id"], "filename": meta["filename"],
            "uploaded_by": meta["uploaded_by"],
            "allowed_roles": meta["allowed_roles"].split(",")
        }
    return list(unique.values())
