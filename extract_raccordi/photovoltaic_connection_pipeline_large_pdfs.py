# pip install pymupdf pdfplumber rank-bm25 sentence-transformers spacy pandas numpy scikit-learn
# python -m spacy download it_core_news_sm

from typing import List, Dict, Any, Tuple
import re
import os
import sys
import json
import numpy as np
import pandas as pd
import spacy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


nlp = spacy.load("it_core_news_sm")

#os.environ["HF_HUB_ETAG_TIMEOUT"] = "30"     # metadata check timeout
#os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60" # actual file download timeout

#huggingface-cli download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
#    --local-dir ./models/paraphrase-multilingual-MiniLM-L12-v2 \
#    --resume-download
#embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
embedder = SentenceTransformer("./models/paraphrase-multilingual-MiniLM-L12-v2")


QUERY = (
    "documenti italiani sulla connessione elettrica di impianti fotovoltaici, "
    "preventivo di connessione, punto di connessione, cabina, tensione MT/AT"
)

BM25_TOP_K = 30
RERANK_TOP_K = 15
RELEVANCE_THRESHOLD = 0.30
EXTRACTABLE_MIN_FIELDS = 3

MAX_TEXT_CHARS_PER_CHUNK = 2000
MIN_TEXT_CHARS_PER_CHUNK = 100
CHUNK_OVERLAP_PAGES = 1


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> List[str]:
    doc = nlp(normalize(text))
    return [
        tok.lemma_
        for tok in doc
        if not tok.is_space and not tok.is_punct and not tok.is_stop
    ]


def detect_ocr_needed(page: fitz.Page) -> bool:
    """Controlla se una pagina necessita OCR (scansioni, senza testo estratto)."""
    text = page.get_text("text")
    return len(text.strip()) < 50


def extract_text_from_pdf_with_ocr(pdf_path: str) -> List[Tuple[int, str]]:
    """Estrae testo dal PDF, applicando OCR solo dove necessario."""
    doc = fitz.open(pdf_path)
    pages_text = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")  # FIX: get_text("text") invece di get_texts("text")

        if detect_ocr_needed(page) and len(text.strip()) < 50:
            # In produzione, integra Tesseract qui:
            # pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            # img_bytes = pix.tobytes("png")
            # text = tesseract_ocr(img_bytes)
            pass

        if text.strip():
            pages_text.append((page_num + 1, text))

    doc.close()
    return pages_text


def chunk_large_document(
    pages_text: List[Tuple[int, str]],
    max_chars: int = MAX_TEXT_CHARS_PER_CHUNK,
    min_chars: int = MIN_TEXT_CHARS_PER_CHUNK,
    overlap_pages: int = CHUNK_OVERLAP_PAGES,
) -> List[Dict[str, Any]]:
    """Chunka un PDF grande per sezioni logiche e confini di pagina."""
    chunks = []
    current_chunk_text = []
    current_chunk_pages = []
    current_len = 0

    for page_num, text in pages_text:
        if current_len + len(text) > max_chars and current_len >= min_chars:
            chunk_text = " ".join(current_chunk_text)
            if len(chunk_text.strip()) >= min_chars:
                chunks.append({
                    "chunk_id": len(chunks) + 1,
                    "start_page": current_chunk_pages[0],
                    "end_page": current_chunk_pages[-1],
                    "text": chunk_text,
                })

            overlap_start = max(0, len(current_chunk_pages) - overlap_pages)
            current_chunk_text = current_chunk_text[overlap_start:]
            current_chunk_pages = current_chunk_pages[overlap_start:]
            current_len = sum(len(t) for t in current_chunk_text)

        current_chunk_text.append(text)
        current_chunk_pages.append(page_num)
        current_len += len(text)

    if current_len >= min_chars:
        chunk_text = " ".join(current_chunk_text)
        if len(chunk_text.strip()) >= min_chars:
            chunks.append({
                "chunk_id": len(chunks) + 1,
                "start_page": current_chunk_pages[0],
                "end_page": current_chunk_pages[-1],
                "text": chunk_text,
            })

    return chunks


def extract_text_from_pdf_chunked(pdf_path: str) -> List[Dict[str, Any]]:
    """Estrae e chunka il testo da un PDF grande."""
    pages_text = extract_text_from_pdf_with_ocr(pdf_path)
    chunks = chunk_large_document(pages_text)
    for chunk in chunks:
        chunk["source_file"] = os.path.basename(pdf_path)
    return chunks


def cosine_similarity(a, b):
    return np.dot(a, b.T)


def build_bm25(corpus_texts: List[str]) -> BM25Okapi:
    tokenized = [tokenize(t) for t in corpus_texts]
    return BM25Okapi(tokenized)


def bm25_retrieve(chunks: List[Dict], bm25: BM25Okapi, query: str, top_k: int) -> List[Dict]:
    q_tokens = tokenize(query)
    scores = bm25.get_scores(q_tokens)

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    top_indices = [idx for idx, score in indexed[:top_k]]
    result = []
    for i, idx in enumerate(top_indices):
        doc = chunks[idx].copy()
        doc["bm25_score"] = float(scores[idx])
        doc["global_rank"] = i + 1
        result.append(doc)

    return result


def semantic_rerank(chunks: List[Dict], query: str) -> List[Dict]:
    texts = [c["text"] for c in chunks]
    doc_emb = embedder.encode(texts, normalize_embeddings=True)
    q_emb = embedder.encode([query], normalize_embeddings=True)
    scores = cosine_similarity(doc_emb, q_emb).ravel()

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    result = []
    for rank, (idx, score) in enumerate(indexed):
        doc = chunks[idx].copy()
        doc["semantic_score"] = float(score)
        doc["rerank_rank"] = rank + 1
        result.append(doc)

    return result


def extract_fields(text: str) -> Dict[str, Any]:
    t = normalize(text)

    voltage_pattern = r"\b(?:at|mt|bt|alta\s+tensione|media\s+tensione|bassa\s+tensione)\b"
    pod_pattern = r"\bpod\b\s*[=:]\s*([A-Z0-9]+)"
    date_pattern = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    operator_pattern = r"\b(?:e-distribuzione|terna|areti|distributore|gestore\s+di\s+rete)\b"

    fields = {
        "mentions_connessione": any(k in t for k in ["connessione", "allacciamento", "collegamento"]),
        "mentions_preventivo": any(k in t for k in ["preventivo di connessione", "preventivo", "richiesta di connessione"]),
        "mentions_voltage": bool(re.search(voltage_pattern, t, re.IGNORECASE)),
        "voltage_value": re.search(voltage_pattern, t, re.IGNORECASE).group(0) if re.search(voltage_pattern, t, re.IGNORECASE) else None,
        "mentions_connection_point": any(k in t for k in ["punto di connessione", "cabina di consegna", "cabina primaria", "stazione utente"]),
        "mentions_grid_operator": bool(re.search(operator_pattern, t, re.IGNORECASE)),
        "operator_name": re.search(r"(?:e-distribuzione|terna|areti)\b", t, re.IGNORECASE).group(0) if re.search(r"(?:e-distribuzione|terna|areti)\b", t, re.IGNORECASE) else None,
        "mentions_dates": bool(re.search(date_pattern, t)),
        "mentions_codes": bool(re.search(r"\bpod\b", t, re.IGNORECASE)),
        "pod_code": re.search(pod_pattern, t, re.IGNORECASE).group(1) if re.search(pod_pattern, t, re.IGNORECASE) else None,
    }

    score = sum([
        fields["mentions_connessione"],
        fields["mentions_preventivo"],
        fields["mentions_voltage"],
        fields["mentions_connection_point"],
        fields["mentions_grid_operator"],
        fields["mentions_dates"],
        fields["mentions_codes"],
    ])
    fields["extractable"] = score >= EXTRACTABLE_MIN_FIELDS
    fields["extractable_score"] = int(score)
    return fields


def process_single_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    chunks = extract_text_from_pdf_chunked(pdf_path)
    if not chunks:
        return []

    bm25 = build_bm25([c["text"] for c in chunks])
    stage1 = bm25_retrieve(chunks, bm25, QUERY, BM25_TOP_K)
    stage2 = semantic_rerank(stage1, QUERY)
    stage2 = stage2[:RERANK_TOP_K]

    for chunk in stage2:
        fields = extract_fields(chunk["text"])
        chunk.update(fields)
        chunk["relevant"] = chunk["semantic_score"] >= RELEVANCE_THRESHOLD

    return stage2


def process_multiple_pdfs(pdf_paths: List[str], max_workers: int = 4) -> List[Dict[str, Any]]:
    all_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_pdf, p): p for p in pdf_paths}
        for future in as_completed(futures):
            pdf_path = futures[future]
            try:
                results = future.result()
                for r in results:
                    r["source_file"] = os.path.basename(pdf_path)
                all_results.extend(results)
            except Exception as e:
                print(f"Errore durante l'elaborazione di {pdf_path}: {e}")

    all_results.sort(key=lambda x: (x["semantic_score"], x["extractable"]), reverse=True)
    return all_results


def save_results(results: List[Dict], output_dir: str) -> None:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(results)
    df.to_csv(out_path / "photovoltaic_connection_results.csv", index=False)

    json_path = out_path / "photovoltaic_connection_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Salvati {len(results)} chunk su {out_path}")

def save_part_results(results: List[Dict], output_dir: str) -> None:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(results)
    df.to_csv(out_path / "partial_results.csv", index=False)

    json_path = out_path / "partial_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Salvati {len(results)} chunk su {out_path}")


def main():
    pdf_dir = sys.argv[1]
    #(
    #	"/home/kathleen/90_DATA_PREPROCESS/italy_poc"
    #	"/italy_poc/output/documents"
    #	"/8133"
    #)
    output_dir = sys.argv[2] #"data/_8133"

    pdf_files = list(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        print(f"Nessun PDF trovato in {pdf_dir}.")
        print(f"Posiziona i tuoi PDF in {pdf_dir}/ e riavvia.")
        return

    results = process_multiple_pdfs([str(p) for p in pdf_files])
    relevant_results = [r for r in results if r["relevant"]]
    extractable_results = [r for r in relevant_results if r["extractable"]]

    print(f"\nChunk totali elaborati: {len(results)}")
    print(f"Chunk rilevanti: {len(relevant_results)}")
    print(f"Chunk estraibili: {len(extractable_results)}")

    if extractable_results:
        print("\nTop 10 chunk estraibili:")
        for r in extractable_results[:10]:
            print(f"\nFile: {r['source_file']}")
            print(f"Pagine: {r['start_page']}-{r['end_page']}")
            print(f"Score: {r['semantic_score']:.3f}, Estraibile: {r['extractable']}")
            print(f"Tensione: {r.get('voltage_value')}, Operatore: {r.get('operator_name')}, POD: {r.get('pod_code')}")
        save_part_results(extractable_results[:10], output_dir)
       

    save_results(results, output_dir)


if __name__ == "__main__":
    main()
