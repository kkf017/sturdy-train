""" Module to ... """

import os
import time
import logging
import shutil
import pdfplumber


ROOT_DIR = "/home/kathleen/90_DATA_PREPROCESS/italy_poc"
FILEPATH = (
	f"{ROOT_DIR}"
	"/italy_poc/output/documents"
	"/8018"
	"/8018_Parere_n_69_Plenaria_PNIEC_del_17_10_22_-_ID_VIP_7380.pdf"
)

FILEPATH = (
	f"{ROOT_DIR}"
	"/extract_pipeline/data/pdfs"
	"/8018_01_R01_Relaz_tecn.pdf"
)

def convert_pdf(filepath):
	filetext = filepath.replace(".pdf", ".txt")
	try:
		with pdfplumber.open(filepath) as pdf, open(filetext, "w", encoding="utf-8") as f: 
			for page in pdf.pages:
				var = page.extract_text()
				if var:
					f.write(var + '\n')
	except:
		pass


def main():
    print(f"Working dir: {FILEPATH}\n")
    	
    convert_pdf(FILEPATH)
    		
    print("\n")


if __name__ == "__main__":
    main()
