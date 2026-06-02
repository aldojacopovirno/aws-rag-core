import boto3
import logging
from botocore.exceptions import BotoCoreError, ClientError
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection

logger = logging.getLogger(__name__)

class AWSClientManager:
    """
    Gestisce la creazione e la fornitura di client boto3 e OpenSearch.
    
    Garantisce l'inizializzazione corretta della sessione AWS e fornisce
    metodi comodi per accedere ai vari servizi (Bedrock, OpenSearch, S3).
    """
    
    def __init__(self, region_name: str = 'eu-central-1'):
        """
        Inizializza il gestore dei client AWS.
        
        Parameters
        ----------
        region_name : str
            La regione AWS su cui effettuare le chiamate.
        """
        self.region_name = region_name
        try:
            self.session = boto3.Session(region_name=self.region_name)
        except Exception as e:
            logger.error(f"Impossibile inizializzare la sessione boto3: {e}")
            raise
            
    def get_boto3_client(self, service_name: str):
        """
        Restituisce un client boto3 generico per il servizio richiesto.
        
        Parameters
        ----------
        service_name : str
            Il nome del servizio AWS (es. 'bedrock-agent-runtime').
            
        Returns
        -------
        botocore.client.BaseClient
            L'istanza del client del servizio specificato.
        """
        return self.session.client(service_name)
        
    def get_opensearch_client(self, collection_endpoint: str) -> OpenSearch:
        """
        Inizializza e restituisce un client per Amazon OpenSearch Serverless (AOSS).
        
        Parameters
        ----------
        collection_endpoint : str
            L'endpoint host della collezione AOSS (es. 'xxx.eu-central-1.aoss.amazonaws.com').
            
        Returns
        -------
        OpenSearch
            L'istanza del client OpenSearchPy configurata per AOSS.
        """
        credentials = self.session.get_credentials()
        aws_auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            self.region_name,
            'aoss',
            session_token=credentials.token
        )
        
        # Rimuove il prefisso https:// se presente accidentalmente
        if collection_endpoint.startswith('https://'):
            collection_endpoint = collection_endpoint[8:]
            
        client = OpenSearch(
            hosts=[{'host': collection_endpoint, 'port': 443}],
            http_auth=aws_auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
        )
        return client
