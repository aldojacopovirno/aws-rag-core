import os
import sys
import json
import argparse
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config_manager import ConfigManager
from core.aws_client import AWSClientManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    """
    Interfaccia CLI per interrogare il sistema RAG.
    Usa argomenti dinamici basati sui filtri configurati.
    """
    config_manager = ConfigManager()
    aws_manager = AWSClientManager()
    
    schema_fields = config_manager.get_metadata_fields()
    
    parser = argparse.ArgumentParser(description="CLI Client per Enterprise RAG System")
    parser.add_argument("query", type=str, help="Query testuale dell'utente")
    parser.add_argument("--model", type=str, default="eu.amazon.nova-pro-v1:0", help="Modello LLM (Bedrock)")
    
    # Aggiungi argomenti CLI in base allo schema dinamico
    for field in schema_fields:
        f_name = field['name']
        f_type = field['type']
        if f_type == 'float' or f_type == 'integer':
            parser.add_argument(f"--{f_name}", type=float, default=None, help=f"Filtro opzionale: {f_name}")
        else:
            parser.add_argument(f"--{f_name}", type=str, default=None, help=f"Filtro opzionale: {f_name}")
            
    args = parser.parse_args()
    
    kb_id = config_manager.get_aws_config("KNOWLEDGE_BASE_ID")
    if not kb_id:
        logger.error("KNOWLEDGE_BASE_ID mancante nella configurazione.")
        sys.exit(1)
        
    agent_runtime = aws_manager.get_boto3_client('bedrock-agent-runtime')
    bedrock_runtime = aws_manager.get_boto3_client('bedrock-runtime')
    
    # Costruzione Filtri
    conditions = []
    args_dict = vars(args)
    for field in schema_fields:
        f_name = field['name']
        val = args_dict.get(f_name)
        if val is not None:
            if field['type'] in ['float', 'integer']:
                # Assumption: simple equality per MVP CLI
                conditions.append({"equals": {"key": f_name, "value": val}})
            else:
                conditions.append({"equals": {"key": f_name, "value": str(val)}})
                
    retrieval_config = {'vectorSearchConfiguration': {'numberOfResults': 6}}
    if conditions:
        if len(conditions) == 1:
            retrieval_config['vectorSearchConfiguration']['filter'] = conditions[0]
        else:
            retrieval_config['vectorSearchConfiguration']['filter'] = {"andAll": conditions}

    logger.info("--- Esecuzione Retrieval da Knowledge Base ---")
    try:
        ret_response = agent_runtime.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={'text': args.query},
            retrievalConfiguration=retrieval_config
        )
    except Exception as e:
        logger.error(f"Errore Retrieval: {e}")
        sys.exit(1)
        
    results = ret_response.get('retrievalResults', [])
    logger.info(f"Trovati {len(results)} chunk rilevanti.")
    
    context_parts = []
    for i, r in enumerate(results):
        text = r['content']['text']
        metadata = r.get('metadata', {})
        meta_str = ", ".join([f"{k}: {v}" for k, v in metadata.items() if v is not None])
        context_parts.append(f"--- Record {i+1} ---\nDescrizione: {text}\nMetadati: {meta_str}\n")
        
    context_str = "\n".join(context_parts) if context_parts else "Nessun risultato."
    
    prompt = f"Contesto RAG:\n<context>\n{context_str}\n</context>\nDomanda utente: {args.query}"
    sys_prompt = "Sei un assistente specializzato. Rispondi con precisione basandoti esclusivamente sul contesto fornito."
    
    logger.info("--- Invocazione LLM Bedrock Converse API ---")
    try:
        response = bedrock_runtime.converse(
            modelId=args.model,
            messages=[{'role': 'user', 'content': [{'text': prompt}]}],
            system=[{'text': sys_prompt}],
            inferenceConfig={'temperature': 0.1, 'maxTokens': 1500}
        )
        reply = response['output']['message']['content'][0]['text']
        print("\n=== Risposta LLM ===")
        print(reply)
        print("====================\n")
    except Exception as e:
        logger.error(f"Errore Converse API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
