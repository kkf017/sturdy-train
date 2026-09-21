import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

def estrai_informazioni(testo: str, template: dict) -> dict:
    # Load NuExtract3 (4B parameters)
    model_id = "numind/NuExtract3"
    
    print("Caricamento del modello e del tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, 
        torch_dtype=torch.bfloat16, 
        device_map="auto", 
        trust_remote_code=True
    )
    
    # Format the prompt using the strict schema expected by NuExtract
    schema_str = json.dumps(template, indent=4)
    prompt = f"<|input|>\n### Template:\n{schema_str}\n### Text:\n{testo}\n<|output|>\n"
    
    # Tokenize input and move to GPU/CPU automatically
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    
    print("Estrazione dei dati in corso...")
    with torch.no_grad():
        outputs = model.generate(
            **inputs, 
            max_new_tokens=1000, 
            eos_token_id=tokenizer.eos_token_id
        )
    
    # Decode the newly generated tokens
    prediction = tokenizer.decode(outputs[inputs.input_ids.shape:], skip_special_tokens=True)
    
    try:
        return json.loads(prediction)
    except json.JSONDecodeError:
        print("Attenzione: L'output del modello non è un JSON valido. Output grezzo:")
        return prediction

# --- Esempio di utilizzo (Italian Document) ---
if __name__ == "__main__":
    # Testo non strutturato in Italiano (Esempio Ricevuta/Fattura)
    documento_italiano = """
    Spett.le Rossi SRL,
    Vi inviamo la presente per sollecitare il pagamento della fattura proforma n. FATT-2026-440 
    relativa ai servizi di consulenza IT forniti nel mese scorso. 
    L'importo totale da saldare è di € 3.450,00 (IVA inclusa).
    
    La scadenza tassativa per il bonifico è fissata per il 30 Ottobre 2026. 
    Per qualsiasi chiarimento in merito alla contabilità, potete contattare direttamente 
    il nostro responsabile amministrativo Marco Bianchi all'indirizzo m.bianchi@techsolutions.it.
    """

    # Nota: Le chiavi del template possono essere scritte sia in inglese che in italiano. 
    # Il modello mappa correttamente il testo italiano ai campi strutturati.
    schema_estrazione = {
        "numero_fattura": "",
        "totale_da_pagare": "",
        "data_scadenza": "",
        "contatto_amministrativo": {
            "nome": "",
            "email": ""
        }
    }

    # Esegui l'estrazione
    risultato_json = estrai_informazioni(documento_italiano, schema_estrazione)
    
    print("\n--- Risultato JSON Estratto ---")
    print(json.dumps(risultato_json, indent=4, ensure_ascii=False))

