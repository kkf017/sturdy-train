"""
Script to remove files .pdf that are less than 2 pages.
"""

import os
import sys
import PyPDF2

NR_PROJ = sys.argv[1] #"11280"

ROOT_DIR = (
	"/home/kathleen/90_DATA_PREPROCESS"
)
PDF_DIR = (
	f"{ROOT_DIR}"
        "/italy_poc/output/documents/"
        f"{NR_PROJ}"
)


def get_num_pages(filepath: str) -> int | None:
	try:
		with open(filepath,'rb') as freader:
			pdfReader = PyPDF2.PdfReader(freader)
			return int(len(pdfReader.pages))
	except Exception as err:
		print(f"Error when reading file. {err}")
		return None

def main() -> None:
	for f in os.listdir(PDF_DIR):
		filepath = os.path.join(PDF_DIR, f)
		n = get_num_pages(filepath=filepath)
		print(f"\n{f} ---> {n}")
		if n is None:
			pass
		elif n < 3:
			os.remove(filepath)
			print(f"Removing file: {f}")
		else:
			pass


if __name__ == "__main__":
	main()

