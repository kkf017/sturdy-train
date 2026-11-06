"""
Script to execute pipeline to extract extra information for wind.
"""
import os
import sys
import time
import json
import sqlite3
import pandas

DB = (
	"./data/wind_projects.db"
)

RACCORDI = (
	"./data/wind_connections_extract.xlsx"
)

SAVE_FILE = (
	"./data/wind_extra_infos.xlsx"
)

#################################################
#
def load_database(filename: str, table: str) -> pandas.DataFrame:
    """
    Function to extract database (table).
    """
    frame = None
    try:
        conn = sqlite3.connect(filename)
        frame = pandas.read_sql_query(f"""SELECT * FROM {table};""", conn, params=())
        conn.close()
        #print(f"Successful extraction. {frame.shape}")
    except sqlite3.OperationalError as err:
        print(f"Failed extraction. {err}")
        sys.exit(-1)
    return frame

def read_xlsx(filename:str) -> pandas.DataFrame:
	"""
	Function to read a file (.xlsx).
	"""
	x = pandas.DataFrame([])
	try:
		x = pandas.read_excel(filename)
	except OSError as err:
		print(f"Error when reading file (.xlsx). {err}")
	return x

def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
	"""
	Function to write a file (.xlsx).
	"""
	try:
		x.to_excel(filename, index=False)
	except OSError as err:
		print(f"Error when writing file. {err}")

#################################################

def get_pdf_url(ids:int, value:str, frame:pandas.DataFrame) -> pandas.core.indexes.base.Index:
	"""
	Function to get the pdf url.
	"""
	#print(value)
	
	# filter with id number of project
	mask = frame['file_name'].apply(lambda x: x in value)
	matches = frame[mask]
	indices = matches.index

	#condition = frame.loc[indices, 'project_id'] == str(ids)
	#filtered_indices = indices[condition]
	#return matches.index
	#return filtered_indices
	
	mask = frame['file_name'].apply(lambda x: x in value) & (frame['project_id']==str(ids))
	filtered_indices = frame.index[mask]
	return filtered_indices


def get_extra_infos(url:str, pdf_name:str) -> None:
	"""
	Function to get extra informations from .pdf (url).
	"""
	filename = f"./output/{pdf_name.replace('.pdf','.json')}"
	command = f"uv run python extract_wind/wind_extract_infos_from_urls_2.py {url} -o {filename}"
	os.system(command)
	time.sleep(3)
	data = {}
	try:
		with open(filename, "r") as file:
	    		data = json.load(file)
		os.remove(filename)
	except Exception as err:
		print(f"Error when getting extra information. {err}")
	return data

def main() -> None:
	# read wind_connections_extract.xlsx
	connections = read_xlsx(filename=RACCORDI)
	print(f"Extract raccordi: {connections.shape}")
	
	# read projects.db -
	projects = load_database(filename=DB, table="documents") 
	print(f"Extract projects: {projects.shape}")
	
	# read wind_extra_infos.xlsx
	# extra_infos = read_xlsx(filename=SAVE_FILE)

	rows = []
	for i, row in connections.iterrows():
		print(f"\n\n")
		for column in ["doc_1", "doc_2","doc_3","doc_4","doc_5"]:
			if not pandas.isna(row[column]):
				indices = get_pdf_url(
					ids=row["nr_proj"], 
					value=row[column], 
					frame=projects
				)
				#print(f"{row[column]} ---> {indices}")
				for index in indices:
					print(f"Get extra infos for: {row['nr_proj']}, {row[column]}.")
					new = {
						"project_id": row["nr_proj"],
						"file_name": row[column],
						"pdf_url": projects.loc[index, "original_url"],
						
						"turbine_model": None,
						"manufacturer": None,
						"number_of_turbines": None,
						"rated_power_MW": None,
						"hub_height_m": None,
						"rotor_diameter_m": None,
						"blade_length_m": None,
						"total_tip_height_m": None,
						"ground_clearance_m": None,
						"authorized": None,
						"pdf_authorization": None
					}
					
					infos = get_extra_infos(
						url=projects.loc[index, "original_url"],
						pdf_name=row[column]
					)
					for key, value in infos.items():
						new[key] = value
					rows.append(new)
					# final_table = pandas.concat([
					#	extra_infos, 
					#	pandas.DataFrame()
					#], ignore_index=True)
				write_xlsx(filename=SAVE_FILE, x=pandas.DataFrame(rows))
				time.sleep(3) 

if __name__ == "__main__":
    main()
