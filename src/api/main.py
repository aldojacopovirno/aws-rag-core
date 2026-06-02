import os
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure correct import paths when running from the project root
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config_manager import ConfigManager
from core.aws_client import AWSClientManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Enterprise RAG API",
    description="API Gateway for Bedrock Knowledge Base RAG system.",
    version="1.0.0"
)

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    """
    Rappresenta la richiesta in ingresso all'API.
    'filters' accetta dizionari chiave-valore per filtrare la ricerca nella Knowledge Base.
    """
    query: str = Field(..., description="La domanda dell'utente.")
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Filtri opzionali basati sui metadati del dominio.")

class ChatResponse(BaseModel):
    """
    Rappresenta la risposta generata dall'LLM.
    """
    reply: str = Field(..., description="Risposta generata dal modello.")

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Endpoint primario per interrogare il sistema RAG.
    
    1. Legge la configurazione e le chiavi AWS.
    2. Costruisce i filtri metadati dinamicamente in base allo schema.
    3. Esegue il retrieval dalla Knowledge Base.
    4. Genera una risposta tramite Bedrock Converse API.
    
    Parameters
    ----------
    request : ChatRequest
        Payload contenente la query testuale e i filtri applicabili.
        
    Returns
    -------
    ChatResponse
        Risposta strutturata contenente l'output testuale dell'LLM.
    """
    try:
        # Inizializzazione Configurazione e Client AWS
        config_manager = ConfigManager(
            config_file_path='config/app_config.json',
            schema_file_path='config/domain_schema.json'
        )
        aws_manager = AWSClientManager()
        
        kb_id = config_manager.get_aws_config("KNOWLEDGE_BASE_ID")
        if not kb_id:
            raise ValueError("KNOWLEDGE_BASE_ID non trovato in app_config.json")
            
        agent_runtime = aws_manager.get_boto3_client('bedrock-agent-runtime')
        bedrock_runtime = aws_manager.get_boto3_client('bedrock-runtime')
        
    except Exception as e:
        logger.error(f"Errore di inizializzazione: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Infrastruttura non configurata.")

    # Costruzione dinamica del filtro metadati
    conditions = []
    schema_fields = config_manager.get_metadata_fields()
    
    for field_info in schema_fields:
        field_name = field_info.get("name")
        field_type = field_info.get("type")
        
        if field_name in request.filters and request.filters[field_name] is not None:
            val = request.filters[field_name]
            if field_type in ['float', 'integer'] and isinstance(val, (int, float)):
                # Ad esempio: Se è numerico applichiamo un <= per i prezzi, o >= per punteggi.
                # Per una logica enterprise, si dovrebbe specificare l'operatore nel payload.
                # Qui facciamo un'assunzione basilare o usiamo l'uguaglianza.
                conditions.append({"equals": {"key": field_name, "value": val}})
            else:
                conditions.append({"equals": {"key": field_name, "value": str(val)}})
                
    retrieval_config = {
        'vectorSearchConfiguration': {
            'numberOfResults': 6
        }
    }
    
    if conditions:
        if len(conditions) == 1:
            retrieval_config['vectorSearchConfiguration']['filter'] = conditions[0]
        else:
            retrieval_config['vectorSearchConfiguration']['filter'] = {"andAll": conditions}

    # Fase di Retrieval
    try:
        logger.info(f"Eseguendo retrieval con query: '{request.query}' e config: {retrieval_config}")
        ret_response = agent_runtime.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={'text': request.query},
            retrievalConfiguration=retrieval_config
        )
    except Exception as e:
        logger.error(f"Retrieve fallita: {e}")
        raise HTTPException(status_code=500, detail="Retrieve fallita contattando AWS Bedrock.")
        
    results = ret_response.get('retrievalResults', [])
    
    # Formattazione Contesto
    context_parts = []
    for i, r in enumerate(results):
        text = r['content']['text']
        metadata = r.get('metadata', {})
        meta_str = ", ".join([f"{k}: {v}" for k, v in metadata.items() if v is not None])
        context_parts.append(f"--- Record {i+1} ---\nDescrizione: {text}\nMetadati: {meta_str}\n")
        
    context_str = "\n".join(context_parts) if context_parts else "Nessun record trovato che corrisponda ai criteri."

    prompt = f"""Ecco le informazioni recuperate dal database aziendale che corrispondono ai filtri scelti:

<context>
{context_str}
</context>

Domanda dell'utente: {request.query}
"""

    model_id = "eu.amazon.nova-pro-v1:0"
    system_prompt = "Sei un consulente strategico esperto in analisi dei dati. Fornisci risposte precise e formali in base al contesto fornito."

    # Invocazione LLM
    try:
        response = bedrock_runtime.converse(
            modelId=model_id,
            messages=[{'role': 'user', 'content': [{'text': prompt}]}],
            system=[{'text': system_prompt}],
            inferenceConfig={'temperature': 0.2, 'maxTokens': 1500}
        )
        reply = response['output']['message']['content'][0]['text']
        return ChatResponse(reply=reply)
        
    except Exception as e:
        logger.error(f"Converse API fallita: {e}")
        raise HTTPException(status_code=500, detail="Errore durante la generazione della risposta con Bedrock.")

