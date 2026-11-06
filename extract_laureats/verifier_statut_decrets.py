#!/usr/bin/env python3
"""
verifier_statut_decrets.py

Lit un fichier .xlsx contenant une colonne "URL du document", télécharge chaque
PDF, en extrait le texte, et cherche les expressions "giudizio positivo" /
"giudizio negativo" (issue de compatibilité environnementale VIA italienne).
Écrit un nouveau fichier .xlsx avec une colonne supplémentaire "Avis détecté".

Usage:
    python verifier_statut_decrets.py fichier_entree.xlsx [fichier_sortie.xlsx]

Si fichier_sortie n'est pas fourni, le script utilise
"<fichier_entree>_avis.xlsx".

Le script est conçu pour être robuste et relançable :
- il sauvegarde le résultat au fur et à mesure (tous les N documents) afin de
  ne rien perdre en cas d'interruption ;
- s'il est relancé sur un fichier de sortie déjà partiellement rempli, il ne
  retélécharge pas les lignes déjà traitées (sauf --force).
"""

import sys
import re
import time
import argparse
import logging
from pathlib import Path

import requests
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

# --------------------------------------------------------------------------
# Extraction de texte PDF : on essaie pdfplumber (meilleure extraction),
# puis on retombe sur pypdf si besoin.
# --------------------------------------------------------------------------
try:
    import pdfplumber
    HAVE_PDFPLUMBER = True
except ImportError:
    HAVE_PDFPLUMBER = False

try:
    from pypdf import PdfReader
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False

import io

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

URL_COLUMN_CANDIDATES = ["url_document", "URL du document", "url document", "doc_url", "URL"]
RESULT_COLUMN = "Avis détecté"
DETAIL_COLUMN = "Détail extraction"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

POSITIVE_RE = re.compile(r"giudizio\s+positivo", re.IGNORECASE)
NEGATIVE_RE = re.compile(r"giudizio\s+negativo", re.IGNORECASE)


def find_url_column(df: pd.DataFrame) -> str:
    for candidate in URL_COLUMN_CANDIDATES:
        if candidate in df.columns:
            return candidate
    raise ValueError(
        f"Impossible de trouver la colonne URL. Colonnes disponibles : {list(df.columns)}"
    )


def download_pdf(url: str, timeout: int = 60, max_retries: int = 3) -> bytes | None:
    """Télécharge le contenu binaire à l'URL donnée, avec quelques tentatives."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            log.warning("  Tentative %d/%d échouée pour %s : %s", attempt, max_retries, url, e)
            time.sleep(2 * attempt)
    return None


def extract_text_from_pdf_bytes(content: bytes) -> str:
    """Extrait le texte d'un PDF en mémoire. Retourne '' si échec."""
    text_parts = []

    # 1) pdfplumber (meilleure qualité d'extraction)
    if HAVE_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
            text = "\n".join(text_parts)
            if text.strip():
                return text
        except Exception as e:
            log.debug("pdfplumber a échoué : %s", e)

    # 2) repli sur pypdf
    if HAVE_PYPDF:
        try:
            reader = PdfReader(io.BytesIO(content))
            text_parts = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(text_parts)
            if text.strip():
                return text
        except Exception as e:
            log.debug("pypdf a échoué : %s", e)

    return ""


def detect_avis(text: str) -> tuple[str, str]:
    """
    Cherche 'giudizio positivo' / 'giudizio negativo' dans le texte.
    Retourne (avis, détail) où avis est l'un de :
        "AVIS POSITIF", "AVIS NÉGATIF", "AMBIGU (les deux trouvés)",
        "NON TROUVÉ", "PDF ILLISIBLE / VIDE"
    """
    if not text or not text.strip():
        return "PDF ILLISIBLE / VIDE", "Aucun texte extrait du document"

    pos_matches = POSITIVE_RE.findall(text)
    neg_matches = NEGATIVE_RE.findall(text)
    n_pos, n_neg = len(pos_matches), len(neg_matches)

    if n_pos > 0 and n_neg == 0:
        return "AVIS POSITIF", f"'giudizio positivo' trouvé {n_pos} fois"
    if n_neg > 0 and n_pos == 0:
        return "AVIS NÉGATIF", f"'giudizio negativo' trouvé {n_neg} fois"
    if n_pos > 0 and n_neg > 0:
        # Les deux expressions apparaissent (ex : un avis négatif cité en
        # préambule, puis contredit dans la décision finale, ou l'inverse).
        # On retient la DERNIÈRE occurrence dans le document comme la plus
        # probable, car la clause décisoire "DECRETA" vient généralement en
        # fin de texte.
        last_pos = text.lower().rfind("giudizio positivo")
        last_neg = text.lower().rfind("giudizio negativo")
        probable = "AVIS POSITIF (probable)" if last_pos > last_neg else "AVIS NÉGATIF (probable)"
        return (
            f"AMBIGU - {probable}",
            f"'positivo' x{n_pos}, 'negativo' x{n_neg} — à vérifier manuellement",
        )
    return "NON TROUVÉ", "Aucune des deux expressions n'a été trouvée dans le texte"


def style_output(ws, n_rows: int, n_cols: int, result_col_idx: int):
    """Applique une mise en forme simple et colore la colonne de résultat."""
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"

    green = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    for r in range(2, n_rows + 2):
        cell = ws.cell(row=r, column=result_col_idx)
        cell.font = Font(name="Arial", size=10)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        val = str(cell.value or "")
        if val.startswith("AVIS POSITIF"):
            cell.fill = green
        elif val.startswith("AVIS NÉGATIF"):
            cell.fill = red
        elif val.startswith("AMBIGU") or "NON TROUVÉ" in val or "ILLISIBLE" in val:
            cell.fill = yellow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fichier_entree", help="Fichier .xlsx généré précédemment (avec colonne URL)")
    parser.add_argument("fichier_sortie", nargs="?", default=None, help="Fichier .xlsx de sortie")
    parser.add_argument(
        "--pause", type=float, default=1.5,
        help="Pause (secondes) entre chaque téléchargement, pour ne pas surcharger le serveur (défaut : 1.5s)",
    )
    parser.add_argument(
        "--save-every", type=int, default=10,
        help="Sauvegarde intermédiaire tous les N documents traités (défaut : 10)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Retraite aussi les lignes déjà remplies dans un fichier de sortie existant",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Ne traiter que les N premières lignes (utile pour tester)",
    )
    args = parser.parse_args()

    in_path = Path(args.fichier_entree)
    out_path = Path(args.fichier_sortie) if args.fichier_sortie else in_path.with_name(
        in_path.stem + "_avis.xlsx"
    )

    # Reprise sur un fichier de sortie déjà partiellement traité
    if out_path.exists() and not args.force:
        log.info("Fichier de sortie existant trouvé, reprise du travail : %s", out_path)
        df = pd.read_excel(out_path)
    else:
        df = pd.read_excel(in_path)
        if RESULT_COLUMN not in df.columns:
            df[RESULT_COLUMN] = ""
        if DETAIL_COLUMN not in df.columns:
            df[DETAIL_COLUMN] = ""

    url_col = find_url_column(df)
    total = len(df)
    log.info("Fichier chargé : %d lignes. Colonne URL détectée : '%s'", total, url_col)

    n_done = 0
    for idx, row in df.iterrows():
        existing = str(row.get(RESULT_COLUMN, "") or "")
        if existing and not args.force:
            continue  # déjà traité lors d'une exécution précédente

        if args.limit is not None and n_done >= args.limit:
            break

        url = row.get(url_col)
        log.info("[%d/%d] Traitement : %s", idx + 1, total, url)

        content = download_pdf(url)
        if content is None:
            df.at[idx, RESULT_COLUMN] = "ERREUR TÉLÉCHARGEMENT"
            df.at[idx, DETAIL_COLUMN] = "Échec du téléchargement après plusieurs tentatives"
        else:
            text = extract_text_from_pdf_bytes(content)
            avis, detail = detect_avis(text)
            df.at[idx, RESULT_COLUMN] = avis
            df.at[idx, DETAIL_COLUMN] = detail
            log.info("  -> %s (%s)", avis, detail)

        n_done += 1

        if n_done % args.save_every == 0:
            df.to_excel(out_path, index=False)
            log.info("Sauvegarde intermédiaire effectuée (%d documents traités).", n_done)

        time.sleep(args.pause)

    # Sauvegarde finale avec mise en forme
    df.to_excel(out_path, index=False)
    wb = load_workbook(out_path)
    ws = wb.active
    result_col_idx = list(df.columns).index(RESULT_COLUMN) + 1
    style_output(ws, len(df), len(df.columns), result_col_idx)
    for i, col in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 25
    wb.save(out_path)

    log.info("Terminé. %d documents traités dans cette exécution.", n_done)
    log.info("Résultat écrit dans : %s", out_path)

    # Petit résumé
    counts = df[RESULT_COLUMN].value_counts(dropna=False)
    log.info("Résumé des avis détectés :\n%s", counts.to_string())


if __name__ == "__main__":
    main()
