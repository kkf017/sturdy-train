"""
Script to load a new table () of laureats from:
	https://www.gse.it/servizi-per-te/fonti-rinnovabili/fer-elettriche/graduatorie
"""
from typing import List
import os 
import json
import pandas

#
TABLE_FER = "./gabarit_colonnes.xlsx"

#
NAME = "AS_A_2021_7"
FILENAME = (
	"./ressources_official/"
	f"{NAME}"
	"/Graduatoria_DM2019_Bando7_ASA-TABELLAA.xlsx"
)

SAVE_FILE = (
	"./"
	"new_gabarit_colonnes.xlsx"
)

ERROR_ = {
	'Possesso di un rating di legalità, di cui all’art.5-ter del decreto-legge n. 1 del 2012, convertito dalla legge n. 27 del 2012, pari ad almeno due «stellette»': "Possesso di un rating di legalita (almeno due stellette)",

	'Impianti realizzati su discariche e lotti di discarica chiusi e ripristinati, cave non suscettibili di ulteriore sfruttamento estrattivo per le quali l’Autorità competente al rilascio dell’autorizzazione abbia attestato l’avvenuto completamento delle attività di recupero e ripristino ambientale previste nel titolo autorizzativo nel rispetto delle norme regionali vigenti, nonché su aree, anche comprese nei siti di interesse nazionale, per le quali sia stata rilasciata la certificazione di avvenuta bonifica ai sensi dell’art.242.13, del D.Lgs. 152/2006, ovvero per le quali risulti chiuso il procedimento di cui all’art.242.2, del medesimo D.Lgs': "Impianti realizzati nelle aree identificate come idonee in attuazione dell'art. 20 del decreto legislativo n. 199 del 2021",

	'Impianti realizzati su discariche e lotti di discarica chiusi e ripristinati, cave non suscettibili di ulteriore sfruttamento estrattivo per le quali l’Autorità competente al rilascio dell’autorizzazione abbia attestato l’avvenuto completamento delle attività di recupero e ripristino ambientale previste nel titolo autorizzativo nel rispetto delle norme regionali vigenti, nonché su aree, anche comprese nei siti di interesse nazionale, per le quali sia stata rilasciata la certificazione di avvenuta bonifica ai sensi dell’art.242.13, del D.Lgs. 152/2006, ovvero per le quali risulti chiuso il procedimento di cui all’art.242.2, del medesimo D.Lgs.': "Impianti realizzati nelle aree identificate come idonee in attuazione dell'art. 20 del decreto legislativo n. 199 del 2021",
	
	"Impianti realizzati nelle aree identificate come idonee in attuazione dell’art. 20 del decreto legislativo n. 199 del 2021": "Impianti realizzati nelle aree identificate come idonee in attuazione dell'art. 20 del decreto legislativo n. 199 del 2021",
	
	"L’impianto/intervento ricadente nel perimetro di applicazione dell’articolo 56, comma 3 del D.L. 76/2020, ammissibile agli incentivi nel solo limite della potenza non assegnata agli impianti diversi da quelli di cui allo stesso comma 3, a sensi del comma 4 dello stesso articolo 56": "Impianto/intervento nel perimetro dell'art. 56 comma 3 del D.L. 76/2020",


	"Potenza ai fini dell’adempimento all'obbligo di cui all'art. 11 del D.Lgs. 28/2011 (kW)": "Potenza ai fini dell'adempimento all'obbligo di cui all'art. 11 del D.Lgs. 28/2011 (kW)",
	
	"impianti connessi in parallelo con la rete elettrica e con colonnine di ricarica di auto elettriche, a condizione che la potenza complessiva di ricarica sia non inferiore al 15% della potenza dell’impianto e che ciascuna colonnina abbia una potenza non inferiore a 15 kW": "Impianti connessi in parallelo con la rete elettrica e con colonnine di ricarica di auto",
	
	
	"Aggregati di impianti, di cui all’art.3.10 del DM2019": "Aggregati di impianti (art.3.10 del DM2019)",
	
	"Valore della Tariffa offerta (€/MWh)": "Valore della Tariffa offerta (EUR/MWh)",
	
	"Rimozione integrale della copertura in eternit o comunque contenente amianto su cui è installato l’impianto": "Rimozione integrale della copertura in eternit o comunque contenente amianto su cui e installato l'impianto",
	
	"Interventi di rifacimento integrale e potenziamento su impianti esistenti realizzati in aree agricole sulla medesima area e a parità della superficie di suolo agricolo originariamente occupata": "Interventi di rifacimento integrale e potenziamento su impianti esistenti in aree agricole",
	
	"Presenza di un sistema di accumulo dell’energia a servizio dell’impianto che garantisca almeno una modulazione giornaliera dell’energia elettrica secondo criteri definiti nelle regole operative di cui all’art. 12 del Decreto": "Presenza di un sistema di accumulo dell'energia a servizio dell'impianto",
	
	"Sottoscrizione di contratti di approvvigionamento di energia di lungo termine di durata pari almeno a 10 anni": "Sottoscrizione di contratti di approvvigionamento di energia di lungo termine (>= 10 anni)",
	
	"Fonte / Tipologia": "Fonte / Tecnologia",
	
	"Quota di potenza ammessa ai sensi dell'art.3.8 del Decreto (kW)": "Quota di potenza ammessa ai sensi dell'art. 3.8 del Decreto (kW)",

}

def read_csv(filename: str) -> pandas.DataFrame:
    """
    Subfunction to read a file (csv).
    """
    try:
        return pandas.read_csv(filename, sep=_get_delimiter(filename))
    except OSError as err:
        print(f"Cant read file (csv). {err}")
        return pandas.DataFrame([])


def read_xlsx(filename: str) -> pandas.DataFrame:
    """
    Subfunction to read a file (xlsx).
    """
    x = pandas.DataFrame([])
    try:
        x = pandas.read_excel(filename)
    except OSError as err:
        print(f"{err}")
    return x

def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
    """
    Subfunction to write a file (xlsx).
    """
    try:
        x.to_excel(filename, index=False)
    except OSError as err:
        print(f"Cant write file (xlsx). {err}")



def add_rows(name: str, frame: pandas.DataFrame, table: pandas.DataFrame, err_list: List[str]) -> pandas.DataFrame:
	for i, row in frame.iterrows():
		new = { key: None for key  in table.columns }
		new["Graduatoria_FER"] = name
		for column in frame.columns:
			if column in table.columns:
				new[column] = row[column]
			elif column in err_list:
				new[ERROR_[column]] = row[column]
			else:
				print(f"Error for column {column} ({row['Codice di richiesta FER']}).")
		if not pandas.isna(row['Codice di richiesta FER']):
			table = pandas.concat([table, pandas.DataFrame([new])], ignore_index=True)
			print(f"New row {row['Codice di richiesta FER']}.")
	return table


def get_columns(table: pandas.DataFrame, frame: pandas.DataFrame) -> List[str]:
	count = 0
	err = []
	for column_a in frame.columns:
		flag = False
		for column_b in table.columns:
			#if 0.85 < distance_levenshtein(column_a,column_b):
			if column_a == column_b:
				#print(f"\n{column_a}")
				count += 1
				flag = True
				break
		if not flag:
			err.append(column_a)
	print(f"Common columns: {count} \n{err}")
	return err

def single_pdf(name:str, filename:str, table:str) -> pandas.DataFrame:
	table_fer = read_xlsx(filename=table)
	frame = read_xlsx(filename=filename)
	
	print(f"FER Table : {table_fer.shape} with {len(table_fer.columns)}")
	print(f"New frame : {frame.shape} with {len(frame.columns)}")

	#print("\n")
	err = get_columns(table=table_fer, frame=frame)
	
	#print("\n")
	table_fer = add_rows(name=name, frame=frame,  table=table_fer, err_list=err)
	
	#table_fer = pandas.concat([
	#	table_fer, 
	#	pandas.DataFrame([{ key: None for key  in table_fer.columns }])
	#], ignore_index=True)

	#write_xlsx(filename=SAVE_FILE, x=table_fer)
	return table_fer

def multiple_pdfs() -> None:
	root = "./ressources_official"
	final_table = pandas.DataFrame([])
	for f in os.listdir(root):
		filepath = os.path.join(root, f)
		for filename in os.listdir(filepath):
			if ".xlsx" in filename:
				print(f"\n\n\nGet file: {f}.")
				pdf = os.path.join(filepath, filename)
				table_fer = single_pdf(name=f,filename=pdf, table=TABLE_FER,)
				
				final_table = pandas.concat([
					final_table, 
					table_fer
				], ignore_index=True)

	write_xlsx(filename=SAVE_FILE, x=final_table)	

def main() -> None:
	#single_pdf(name=NAME, filename=FILENAME, table=TABLE_FER)
	multiple_pdfs()

if __name__ == "__main__":
	main()
	
