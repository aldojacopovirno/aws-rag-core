import json
import os
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Gestisce il caricamento delle configurazioni di infrastruttura e di dominio.
    
    Questa classe fornisce un'interfaccia unificata per accedere a variabili
    d'ambiente, configurazioni AWS (es. IDs delle Knowledge Base) e allo schema
    dati specifico del dominio caricato da domain_schema.json.
    """
    
    def __init__(self, config_file_path: str = 'config/app_config.json', schema_file_path: str = 'config/domain_schema.json'):
        """
        Inizializza il ConfigManager.
        
        Parameters
        ----------
        config_file_path : str
            Il percorso del file di configurazione infrastrutturale (AWS resources).
        schema_file_path : str
            Il percorso del file che definisce lo schema dei metadati del dominio.
        """
        self.config_path = config_file_path
        self.schema_path = schema_file_path
        
        self.config_data = self._load_json(self.config_path)
        self.schema_data = self._load_json(self.schema_path)

    def _load_json(self, path: str) -> dict:
        """
        Carica un file JSON se esiste, altrimenti restituisce un dizionario vuoto.
        
        Parameters
        ----------
        path : str
            Il percorso del file da caricare.
            
        Returns
        -------
        dict
            Il contenuto del file JSON, o un dict vuoto in caso di fallimento o assenza.
        """
        if not os.path.exists(path):
            logger.warning(f"File di configurazione non trovato al percorso: {path}")
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Errore durante la lettura del file {path}: {e}")
            return {}

    def get_aws_config(self, key: str, default: str = None) -> str:
        """
        Recupera una chiave di configurazione infrastrutturale AWS.
        
        Parameters
        ----------
        key : str
            Il nome della chiave (es. 'KNOWLEDGE_BASE_ID').
        default : str, optional
            Valore di default restituito se la chiave non viene trovata.
            
        Returns
        -------
        str
            Il valore della chiave o il default.
        """
        return self.config_data.get(key, default)
        
    def get_metadata_fields(self) -> list:
        """
        Restituisce l'elenco dei metadati definiti per il dominio (es. prezzo, paese).
        
        Returns
        -------
        list
            Una lista di dizionari descriventi i campi metadati.
        """
        return self.schema_data.get('metadata_fields', [])

    def get_content_field(self) -> str:
        """
        Restituisce il nome del campo che contiene il testo principale del documento.
        
        Returns
        -------
        str
            Il nome del campo content (es. 'page_content').
        """
        return self.schema_data.get('content_field', 'page_content')
