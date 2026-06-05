"""
Traduction PDF Italien → Français
Préserve la mise en page originale (images, couleurs, positions).

Dépendances :
    pip install pymupdf deep-translator

Usage :
    python translate_pdf.py document_italien.pdf
    python translate_pdf.py document_italien.pdf --output traduit.pdf
    python translate_pdf.py document_italien.pdf --source it --target fr
    
# Cas basique : italian.pdf → italian_traduit.pdf
python translate_pdf.py document_italien.pdf

# Avec un nom de sortie personnalisé
python translate_pdf.py document_italien.pdf --output traduit.pdf

# Vers une autre langue (ex: anglais)
python translate_pdf.py document_italien.pdf --target en
"""

import argparse
import sys
import time

import fitz  # pymupdf
from deep_translator import GoogleTranslator


# ─────────────────────────────────────────────
#  Paramètres ajustables
# ─────────────────────────────────────────────
SOURCE_LANG   = "it"   # langue source (italien)
TARGET_LANG   = "fr"   # langue cible  (français)
FONT_NAME     = "helv" # police de remplacement (helv = Helvetica intégrée dans pymupdf)
SHRINK_RATIO  = 0.92   # facteur de réduction de taille si le texte traduit dépasse
MIN_FONT_SIZE = 6.0    # taille minimale autorisée
BATCH_PAUSE   = 1.0    # pause (s) entre chaque page pour éviter le rate-limiting


def translate_text(translator: GoogleTranslator, text: str) -> str:
    """Traduit un texte, renvoie le texte original en cas d'erreur."""
    text = text.strip()
    if not text or len(text) < 2:
        return text
    try:
        result = translator.translate(text)
        return result if result else text
    except Exception as exc:
        print(f"  ⚠ Erreur traduction : {exc}")
        return text


def fit_font_size(page: fitz.Page, rect: fitz.Rect, text: str,
                  font_name: str, initial_size: float) -> float:
    """Réduit la taille de police jusqu'à ce que le texte tienne dans le rectangle."""
    size = initial_size
    while size >= MIN_FONT_SIZE:
        tw = fitz.get_text_length(text, fontname=font_name, fontsize=size)
        if tw <= rect.width * 1.05:   # 5 % de tolérance
            break
        size *= SHRINK_RATIO
    return max(size, MIN_FONT_SIZE)


def translate_pdf(input_path: str, output_path: str,
                  source: str = SOURCE_LANG, target: str = TARGET_LANG) -> None:

    print(f"\n📄 Ouverture : {input_path}")
    doc = fitz.open(input_path)

    translator = GoogleTranslator(source=source, target=target)

    for page_num, page in enumerate(doc, start=1):
        print(f"\n── Page {page_num}/{len(doc)} ──────────────────")

        # Récupère tous les blocs de texte avec leurs coordonnées et propriétés
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block.get("type") != 0:   # 0 = texte, 1 = image → on ignore les images
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    original_text = span.get("text", "").strip()
                    if not original_text:
                        continue

                    rect       = fitz.Rect(span["bbox"])
                    font_size  = span.get("size", 11)
                    color      = span.get("color", 0)          # couleur en entier RGB
                    flags      = span.get("flags", 0)          # gras / italique
                    origin     = fitz.Point(span["origin"])    # point de base du texte

                    # ── Traduction ──────────────────────────────
                    translated = translate_text(translator, original_text)
                    if translated == original_text:
                        continue   # rien à faire

                    print(f"  [{original_text[:40]!r}] → [{translated[:40]!r}]")

                    # ── Effacement de l'ancien texte ─────────────
                    # On dessine un rectangle blanc (ou de la couleur de fond) par-dessus
                    annot_rect = rect + fitz.Rect(-1, -1, 1, 1)  # légère marge
                    page.draw_rect(annot_rect, color=None, fill=(1, 1, 1), overlay=True)

                    # ── Adaptation de la taille de police ────────
                    fitted_size = fit_font_size(page, rect, translated,
                                                FONT_NAME, font_size)

                    # ── Conversion couleur int → RGB tuple ───────
                    r = ((color >> 16) & 0xFF) / 255
                    g = ((color >> 8)  & 0xFF) / 255
                    b = (color & 0xFF) / 255
                    rgb = (r, g, b)

                    # ── Gras / italique via fontname ──────────────
                    bold   = bool(flags & 2**4)
                    italic = bool(flags & 2**1)
                    if bold and italic:
                        font = "helv-bi"
                    elif bold:
                        font = "helv-b"
                    elif italic:
                        font = "helv-i"
                    else:
                        font = FONT_NAME

                    # ── Insertion du texte traduit ────────────────
                    try:
                        page.insert_text(
                            origin,
                            translated,
                            fontname=font,
                            fontsize=fitted_size,
                            color=rgb,
                            overlay=True,
                        )
                    except Exception as exc:
                        print(f"    ⚠ Impossible d'insérer le texte : {exc}")

        # Petite pause pour ne pas dépasser la limite de l'API gratuite
        if page_num < len(doc):
            time.sleep(BATCH_PAUSE)

    # ── Sauvegarde ───────────────────────────────────────────────────────────
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    print(f"\n✅ PDF traduit sauvegardé : {output_path}")


# ─────────────────────────────────────────────
#  Point d'entrée
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Traduit un PDF en préservant sa mise en page."
    )
    parser.add_argument("input",  help="Chemin vers le PDF source (italien)")
    parser.add_argument("--output", "-o",
                        help="Chemin du PDF traduit (défaut : input_traduit.pdf)")
    parser.add_argument("--source", "-s", default=SOURCE_LANG,
                        help=f"Langue source (défaut : {SOURCE_LANG})")
    parser.add_argument("--target", "-t", default=TARGET_LANG,
                        help=f"Langue cible  (défaut : {TARGET_LANG})")
    args = parser.parse_args()

    output = args.output or args.input.replace(".pdf", "_traduit.pdf")

    try:	
        translate_pdf(args.input, output, source=args.source, target=args.target)
    except:
    	pass
