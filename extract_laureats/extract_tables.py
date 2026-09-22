"""
Script to extract sqlite tables from pdfs.
"""
import os
import time
import json
import pandas
from functools import reduce

ROOT_ = "./ressources_official"


def read_xlsx(filename):
	"""
	Function to read a file (.xlsx).
	"""
	x = pandas.DataFrame([])
	try:
		x = pandas.read_excel(filename)
	except OSError as err:
		print(f"Error when reading file (.xlsx). {err}")
	return x

def create_excel(filename):
	excel = os.path.join(filepath, filename.replace(" ","").strip()).replace(".pdf",".xlsx")
	print(f"{filename} \n{excel}")
	command = f'uv run extract_table.py "{filename}" "{excel}"'	
	os.system(command)
	print(f"Excel file created for {filename}.\n\n")


def get_columns():
	columns = []
	len_columns = []
	for f in os.listdir(ROOT_):
		filepath = os.path.join(ROOT_, f)
		for filename in os.listdir(filepath):
			if ".xlsx" in filename:  # and (not f in ["PC_EOL_2025", "PC_FTV_2025", "PC_FTVNZIA_2025"]):
				filename = os.path.join(filepath, filename)
				frame = read_xlsx(filename)
				
				columns.append({
					"name": f,
					"columns": frame.columns,
					"length": len(frame.columns),
				})
				len_columns.append(len(frame.columns))
				#print(f"\n{f} \n\t{frame.columns}, {len(frame.columns)}")

	unique_columns = []
	for i in range(max(len_columns)):
		print(f"\n\nColumns {i}:")
		a = []
		for j in range(len(columns)):
			try:
				a.append(columns[j]["columns"][i])
			except:
				pass
		print(f"{json.dumps(list(set(a)), indent=8)}")
		unique_columns.append(list(set(a)))
	
	table = []
	print(f"\n\n\n")
	for sub in unique_columns:
		for elmt in sub:
			if not elmt in table:
				table.append(elmt)
				
				names = [sub["name"] for sub in columns if elmt in sub["columns"]]
				input(f"\n\n{elmt} \n\t{names}")
	#print(f"\n\n\n{json.dumps(table, indent=8)}")
		


	# define common columns
	print("\n\n\n")
	common = list(reduce(set.intersection, map(set, columns)))
	#print(json.dumps(common, indent=8))
	#print(len(common))
	
	# define extra columns
	print("\n\n\n")
	diff = list(set([
	    x
	    for lst in columns
	    for x in lst
	    if x not in common
	]))
	#print(json.dumps(diff, indent=8))
	#print(len(diff))

def single_pdf():
	pass

def multiple_pdfs():
	for f in os.listdir(ROOT_):
		filepath = os.path.join(ROOT_, f)
		for filename in os.listdir(filepath):
			#print(filename)
			pdf = os.path.join(filepath, filename)
			
			create_excel(filename=pdf)
			#time.sleep(3)


def main():
	#single_pdf()
	#multiple_pdfs()
	
	get_columns()


if __name__ == "__main__":
	main()
