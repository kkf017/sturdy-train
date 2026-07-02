""" Script to extract Raccordi informations. """

import os
import time
import logging
import pandas
import fitz #pdfplumber
import unidecode
import string

import re
import spacy
from spacy.matcher import Matcher
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc, Span

nlp = spacy.load("fr_core_news_sm")



NR_PROJ = "10036"
FILENAME = "10036_INT-2_FOR_10_2_SIA_1_Sintesi_non_tecnica.pdf"

FILEPATH = (
	"/home/kathleen/90_DATA_PREPROCESS/italy_poc/output/documents"
	f"/{NR_PROJ}"
	f"/{FILENAME}"
)

#########################################################################
#
def read_xlsx(filename: str) -> pandas.DataFrame:
    x = pandas.DataFrame([])
    try:
        x = pandas.read_excel(filename)
    except OSError as err:
        logging.error(f"{err}")
    return x

def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
    try:
        x.to_excel(filename, index=False)
    except OSError as err:
        logging.error(f"Cant write file (xlsx). {err}")

#########################################################################
#
def clean_txt(txt):
	exceptions = {
		"s.teresa": "s teresa",
	}
	try:
		txt = txt.lower()
		txt = txt.replace("\n"," ").replace("\t"," ")
		txt = unidecode.unidecode(txt)
		#translator = str.maketrans(string.punctuation, ' ' * len(string.punctuation))
		#txt = txt.translate(translator)
		for key , value in exceptions.items():
			txt = txt.replace(key, value)
		return txt
	except Exception:
		return txt

def read_large_pdf_pymupdf(pdf_path, max_pages=None, return_pages=False):
    pages_text = []
    with fitz.open(pdf_path) as doc:
        n = len(doc) if max_pages is None else min(max_pages, len(doc))
        for i in range(n):
            text = doc[i].get_text("text")
            pages_text.append(text)
    return pages_text if return_pages else "\n".join(pages_text)

#########################################################################
#

def _extract_connection_line(txt):	
	patterns = [
		[
		    {"TEXT": {"IN": ["rtn", "rtte"]}, "OP": "+"},
		    {"TEXT": {"IN": ["a"]}, "OP": "*"},
		    {"LIKE_NUM": True, "OP": "+"},
		    {"TEXT": {"IN": ["kv"]}, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "+"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['-']}, "OP": "+"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"IS_PUNCT": True, "OP": "*"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "+"}
		],
		[
		    {"TEXT": {"IN": ['"']}, "OP": "+"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['-']}, "OP": "+"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "+"}
		],
		[
		    {"TEXT": {"IN": ["SE", "se"]}, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "?"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "?"},	    
		    {"TEXT": {"IN": ['-']}, "OP": "+"},
		    {"TEXT": {"IN": ["SE", "se"]}, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "?"},
		    {"IS_ASCII": True, "OP": "+"},
		    {"TEXT": {"IN": ['"']}, "OP": "?"},
		],
		
		# rtn 6/180/380kV Bisaccia-Deliceto
	]

	nlp_doc = nlp(txt)
	
	matcher = Matcher(nlp.vocab)
	matcher.add("extract_connection_line", patterns)
	matches = matcher(nlp_doc)
	
	for match_id, start, end in matches:
		print(f"\t\033[33m{nlp.vocab.strings[match_id]}\033[0m, {nlp_doc[start:end]}")


def extract_connection_line(text: str) -> str:
    """
    Extracts the substation name from various Italian phrasing:
    - "Stazione Elettrica (SE) di smistamento" -> 'smistamento'
    - "SE RTN 150/36 kV Caltagirone" -> 'Caltagirone'
    - "cabina primaria AT/MT LEINI" -> 'LEINI'
    """
    
    patterns = [
    	r'linea\s+(?:(?:RTN|MT|AT)\s+)?(?:a\s+\d+\s*kV\s+)?(?:esistente\s+)?(["“\']+[A-Za-zÀ-ÖØ-öø-ÿ\s]+[\-–—]+[A-Za-zÀ-ÖØ-öø-ÿ\s]+["“\']+)',
  	
  	r'linea\s+\d+\s*kV\s+["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]',
  	
  	r"sull['\u2019]esistente\s+elettrodotto\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*\s*[\-\–\—]+\s*[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)",
  	
  	r'(?:SE|se)(?:\s+(?:SE|se))*\s*"?\s*[^\s"]+(?:\s+[^\s"]+)*"?\s*-+\s*(?:SE|se)(?:\s+(?:SE|se))*\s*"?\s*[^\s"]+(?:\s+[^\s"]+)*"?'
  	
  	r'(?:rtn|rtte)(?:\s+(?:rtn|rtte))*(?:\s+a)*\s+\d+(?:\s+\d+)*\s+kv(?:\s+kv)*\s+"+\s*[^\s"]+(?:\s+[^\s"]+)*\s*-+\s*[^\s"]+(?:\s+[^\s"]+)*(?:\s*[^\w\s]+)*\s*[^\s"]+(?:\s+[^\s"]+)*\s*"+',
  	
  	r'\s+\d+(?:\s+\d+)*\s+kv(?:\s+kv)*\s+"+\s*[^\s"]+(?:\s+[^\s"]+)*\s*-+\s*[^\s"]+(?:\s+[^\s"]+)*(?:\s*[^\w\s]+)*\s*[^\s"]+(?:\s+[^\s"]+)*\s*"+',
  	
  	r'\s+"+\s*[^\s"]+(?:\s+[^\s"]+)*\s*-+\s*[^\s"]+(?:\s+[^\s"]+)*(?:\s*[^\w\s]+)*\s*[^\s"]+(?:\s+[^\s"]+)*\s*"+',
  	
  	r'\s+"+\s*[^\s"-]+(?:\s+[^\s"-]+)*\s*-+\s*[^\s"-]+(?:\s+[^\s"-]+)*(?:\s*[^\w\s]+)*\s*[^\s"-]+(?:\s+[^\s"-]+)*\s*"+',
  	
  	r'\s*[^\s"]+(?:\s+[^\s"]+)*\s*-+\s*[^\s"]+(?:\s+[^\s"]+)*(?:\s*[^\w\s]+)*\s*[^\s"]+(?:\s+[^\s"]+)*',
 
    ]
    
#    for pattern in patterns:
#	    try:
#	        clean_text = re.sub(r'\s+', ' ', text)
#	        match = re.search(pattern, clean_text, re.IGNORECASE)
#	    
#	        if match:
#                    print(f'''\t\033[33mregex\033[0m:, {match.group(0).replace("linea", "").strip()[:65]}''')
#                    return match.group(0).replace("linea", "").strip()[:65]
#	    except:
#	    	pass
    for pattern in patterns:
        try:
            clean_text = re.sub(r'\s+', ' ', text)
            for match in re.finditer(pattern, clean_text, re.IGNORECASE | re.VERBOSE):
                print(f"\t\033[35mMatch\033[0m: {match.group()!r}")
                print(f"\t\033[33mPosition\033[0m: {match.start()}–{match.end()}")
        except:
            pass
    return None


#########################################################################
#
EXPRESSIONS = [
]

def _main():
	#txt = read_large_pdf_pymupdf(FILEPATH)
	#txt = clean_txt(txt)
	#print(txt)
	
	for expr in EXPRESSIONS:
		txt = clean_txt(expr)
		print(f"\n\nExpression: {txt}")
		extract_connection_line(txt)


def main():
	filename = (
		"/home/kathleen/90_DATA_PREPROCESS/sturdy-train/output"
		"/[REGEX]_connections_extract.xlsx"
	)
	frame = read_xlsx(filename)
	print(f"Shape: {frame.shape}")
	
	for i, row in frame.iterrows():
		print(f"({i}) {row['nr_proj']}: \n\t{row['connection_line']}")
		try:
			txt = clean_txt(row['connection_line'])
			extract_connection_line(txt)
		except ValueError:
			pass
		#time.sleep(1.5)


if __name__ == "__main__":
    main()
