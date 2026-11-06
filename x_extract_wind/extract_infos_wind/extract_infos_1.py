import json
import torch
from pdf2image import convert_from_path, pdfinfo_from_path
from transformers import AutoModelForCausalLM, AutoTokenizer

# numind/NuExtract3
# microsoft/Phi-3-mini-4k-instruct

# Qwen/Qwen2.5-VL-7B-Instruct
# ibm-granite/granite-docling-258M
# deepseek-ai/DeepSeek-OCR-3B
# PaddleOCR-VL
custom_path = "./NuExtract3"

def merge_extracted_data(global_data: dict, new_data: dict) -> dict:
    """
    Fusionne de manière récursive les nouvelles informations extraites 
    dans le dictionnaire global sans écraser les données déjà trouvées.
    """
    for key, value in new_data.items():
        if not value: # Si la nouvelle valeur est vide, on passe
            continue
        
        if key in global_data:
            if isinstance(global_data[key], dict) and isinstance(value, dict):
                merge_extracted_data(global_data[key], value)
            elif not global_data[key]: # Si l'ancienne valeur était vide, on met à jour
                global_data[key] = value
        else:
            global_data[key] = value
    return global_data

def estrai_da_grande_pdf(pdf_path: str, template: dict) -> dict:
    model_id = "numind/NuExtract3"
    
    print("Caricamento del modello...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, cache_dir=custom_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, 
        torch_dtype=torch.bfloat16, 
        device_map="auto", 
        trust_remote_code=True,
        cache_dir=custom_path
    )
    
    # 1. Obtenir le nombre total de pages sans charger tout le PDF en mémoire
    info = pdfinfo_from_path(pdf_path)
    total_pages = info["Pages"]
    print(f"Il documento contiene {total_pages} pagine.")
    
    # Initialiser le dictionnaire qui contiendra la fusion de toutes les pages
    dati_finali = json.loads(json.dumps(template)) # Copie profonde du template
    
    # 2. Boucler sur chaque page individuellement (Streaming des pages)
    for page_num in range(1, total_pages + 1):
        print(f"\n--- Elaborazione Pagina {page_num} / {total_pages} ---")
        
        # On extrait l'image de la page courante uniquement
        pagine = convert_from_path(pdf_path, first_page=page_num, last_page=page_num)
        immagine_pagina = pagine[0]
        
        # Préparer le prompt NuExtract
        schema_str = json.dumps(template, indent=4)
        prompt = f"<|input|>\n### Template:\n{schema_str}\n### Image:\n<|image|>\n<|output|>\n"
        
        # Préparer les tenseurs
        inputs = tokenizer(prompt, images=[immagine_pagina], return_tensors="pt").to(model.device)
        
        # Inférence locale
        with torch.no_grad():
            outputs = model.generate(
                **inputs, 
                max_new_tokens=1000, 
                eos_token_id=tokenizer.eos_token_id
            )
        
        # Décodage corrigé [0]
        prediction = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        
        try:
            nuovi_dati = json.loads(prediction)
            # Fusionner les données de cette page dans le résultat final
            dati_finali = merge_extracted_data(dati_finali, nuovi_dati)
        except json.JSONDecodeError:
            print(f"Avviso: Errore di parsing JSON alla pagina {page_num}. Salto la pagina.")
            continue
            
    return dati_finali

# --- Esempio di utilizzo ---
if __name__ == "__main__":
    percorso_grande_pdf = (
    	"/home/kathleen/90_DATA_PREPROCESS/italy_poc"
    	"/output/documents"
    	"/10009"
    	"/10009_030-12_04-RelazioneTecnicoDescrittiva.pdf"
    ) 
    
    schema_estrazione = {
        "nome_progetto": "",
        "aerogeneratori": {
            "numero_turbine": "",
            "modello_turbina": "",
            "potenza_nominale": ""
        },
        "dimensioni_tecniche": {
            "altezza_totale": "",
            "altezza_mozzo": "",
            "diametro_rotore": "",
            "lunghezza_pala": ""
        }
    }
    
    try:
        risultato_completo = estrai_da_grande_pdf(percorso_grande_pdf, schema_estrazione)
        print("\n================ RISULTATO FINALE COMPILATO ================")
        print(json.dumps(risultato_completo, indent=8, ensure_ascii=False))
    except FileNotFoundError:
        print(f"Errore: Inserisci il tuo file '{percorso_grande_pdf}' nella cartella.")

