#!/usr/bin/env python3
import re
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import fitz
import pandas as pd


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u00ad", "")
    text = text.replace("\n", " ")
    text = re.sub(r"-\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_pdf_pages(pdf_path: str) -> List[str]:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        try:
            pages.append(normalize_text(page.get_text("text")))
        except Exception:
            pages.append("")
    return pages


def extract_pdf_text(pdf_path: str) -> str:
    return normalize_text(" ".join(extract_pdf_pages(pdf_path)))


SECTION_KEYWORDS = [
    "rtn",
    "se rtn",
    "sottostazione",
    "cabina",
    "stmg",
    "terna",
    "comune di",
    "ubicata nel comune",
    "linea",
    "cavo",
]


def relevant_window(text: str, size: int = 10000) -> str:
    lower = text.lower()
    positions = [lower.find(k) for k in SECTION_KEYWORDS if lower.find(k) != -1]
    if not positions:
        return text[:size]
    start = max(0, min(positions) - 1500)
    end = min(len(text), max(positions) + size)
    return text[start:end]


def clean_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-")
    return value or None


def first_match(pattern: str, text: str, flags=re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return clean_value(m.group(1)) if m else None


def extract_substation_name(text: str) -> Optional[str]:
    patterns = [
        r"\bSE\s+RTN\s+(\d{2,3}\s*/\s*\d{2,3}\s*kV\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9' \-]+)",
        r"\bSE\s+RTN\s+(\d{2,3}\s*/\s*\d{2,3}\s*kV\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9' \-]+)",
        r"\bS(E|ottostazione)\s+RTN\s+(\d{2,3}\s*/\s*\d{2,3}\s*kV\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9' \-]+)",
        r"\bSE\s+RTN\s+\d{2,3}\s*/\s*\d{2,3}\s*kV\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9' \-]+)",
        r"\b(?:SE|sottostazione)\s+(?:RTN\s+)?[^\n,;]*?\b([A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9' \-]{3,})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            g = m.group(1) if m.lastindex == 1 else m.group(m.lastindex)
            if g and "linea" not in g.lower():
                return clean_value(g)
    return None


def extract_substation_code(text: str) -> Optional[str]:
    patterns = [
        r"\bcodice\s*[:\-]?\s*([A-Z0-9]{6,})",
        r"\bIDVIP\s*[:\-]?\s*([A-Z0-9]{4,})",
        r"\b(?:pratica|protocollo|cod\.)\s*[:\-]?\s*([A-Z0-9]{6,})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return clean_value(m.group(1))
    return None


def extract_voltage_kv(text: str) -> Optional[float]:
    patterns = [
        r"\b(?:in\s+antenna\s+a\s+)?(\d{2,3}(?:[\,\.]\d+)?)\s*kV\b",
        r"\b(?:connessione|linea|cavo)\s+.*?\b(\d{2,3}(?:[\,\.]\d+)?)\s*kV\b",
        r"\bSE\s+RTN\s+(\d{2,3}(?:[\,\.]\d+)?)\s*/\s*(\d{2,3}(?:[\,\.]\d+)?)\s*kV\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            val = m.group(1).replace(",", ".")
            return float(val)
    return None


def extract_connection_type(text: str) -> Optional[str]:
    patterns = [
        r"\b(connection|connessione)\s+(?:type\s*)?[:\-]?\s*([A-Z0-9/ \-]+)",
        r"\bin\s+antenna\s+a\s+(\d{2,3}\s*kV)\b",
        r"\b(in\s+antenna|entra-esce|RTN|MT|AT/?MT)\b",
    ]
    m = re.search(r"\bin\s+antenna\s+a\s+\d{2,3}\s*kV\b", text, flags=re.IGNORECASE)
    if m:
        return "in antenna"
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            if m.lastindex and m.lastindex >= 2:
                return clean_value(m.group(2))
            return clean_value(m.group(1))
    return None


def extract_cable_length_km(text: str) -> Optional[float]:
    candidates = []

    for m in re.finditer(r"\b(\d{3,6})\b", text):
        v = int(m.group(1))
        if 1000 <= v <= 50000:
            candidates.append(v / 1000.0)

    for m in re.finditer(r"(?:circa\s+)?(\d+(?:[\,\.]\d+)?)\s*(km|m)\b", text, flags=re.IGNORECASE):
        val = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        candidates.append(val if unit == "km" else val / 1000.0)

    if not candidates:
        return None

    candidates = [x for x in candidates if 0.1 <= x <= 100]
    return max(candidates) if candidates else None


def extract_connection_municipality(text: str) -> Optional[str]:
    patterns = [
        r"ubicat[oa]\s+nel\s+Comune\s+di\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ' \-]+)",
        r"nel\s+Comune\s+di\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ' \-]+)\s*\((?:CT|TO|PA|RG|ME|SR|EN|CL|TP|AG|TP)\)",
        r"(?:Comune di|Comuni di)\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ' \-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return clean_value(m.group(1))
    return None


def extract_terna_approved(text: str) -> Optional[bool]:
    lower = text.lower()
    if "terna" not in lower and "rtn" not in lower:
        return None
    if re.search(r"(benestariat[oa]?|approvat[oa]?|accettat[oa]?|nulla osta|rilasciat[oa]?)", lower):
        return True
    if re.search(r"(non\s+benestariat[oa]?|non\s+approvat[oa]?|rigettat[oa]?|respint[oa]?)", lower):
        return False
    return None


def extract_stmg_accepted(text: str) -> Optional[bool]:
    lower = text.lower()
    if "stmg" not in lower and "soluzione tecnica minima generale" not in lower:
        return False
    if re.search(r"(stmg|soluzione tecnica minima generale).*(accettat|approvat|condivis|recepit)", lower):
        return True
    if re.search(r"(non\s+accettat|respint|rigettat).*(stmg|soluzione tecnica minima generale)", lower):
        return False
    return False


def extract_shared_connection(text: str) -> Optional[bool]:
    lower = text.lower()
    if re.search(r"(in capo ad altro produttore capofila|shared|condivis[oa]|unica stazione|unico punto di connessione)", lower):
        return True
    if re.search(r"(non\s+condivis|in maniera indipendente|separate|autonome)", lower):
        return False
    return False


def extract_row_from_pdf(pdf_path: str) -> Dict[str, object]:
    pages = extract_pdf_pages(pdf_path)
    full_text = " ".join(pages)
    window = relevant_window(full_text)

    return {
        "source_file": Path(pdf_path).name,
        "substation_name": extract_substation_name(window),
        "substation_code": extract_substation_code(full_text),
        "voltage_kv": extract_voltage_kv(window),
        "connection_type": extract_connection_type(window),
        "cable_length_km": extract_cable_length_km(full_text),
        "connection_municipality": extract_connection_municipality(full_text),
        "terna_approved": extract_terna_approved(full_text),
        "stmg_accepted": extract_stmg_accepted(full_text),
        "shared_connection": extract_shared_connection(full_text),
    }


def process_folder(input_dir: str, output_csv: str, output_json: str) -> pd.DataFrame:
    rows = []
    for pdf_path in sorted(Path(input_dir).glob("*.pdf")):
        try:
            rows.append(extract_row_from_pdf(str(pdf_path)))
        except Exception as e:
            rows.append({
                "source_file": pdf_path.name,
                "substation_name": None,
                "substation_code": None,
                "voltage_kv": None,
                "connection_type": None,
                "cable_length_km": None,
                "connection_municipality": None,
                "terna_approved": None,
                "stmg_accepted": None,
                "shared_connection": None,
                "error": str(e),
            })

    df = pd.DataFrame(rows)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return df


if __name__ == "__main__":
    input_dir = "data/pdfs"
    output_csv = "output/connection_extraction.csv"
    output_json = "output/connection_extraction.json"
    df = process_folder(input_dir, output_csv, output_json)
    print(df.to_string(index=False))
