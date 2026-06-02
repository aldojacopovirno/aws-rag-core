import json
import sys
import time
import argparse
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.aws_client import AWSClientManager
from core.config_manager import ConfigManager

def create_aoss_resources(collection_name: str, index_name: str):
    """
    Effettua il provisioning dell'infrastruttura Amazon OpenSearch Serverless (AOSS).
    Crea Security Policies (Encryption, Network, Data Access), la Collection AOSS,
    e definisce l'Index basandosi dinamicamente sullo schema di dominio configurato.
    
    Parameters
    ----------
    collection_name : str
        Nome desiderato per la collezione AOSS.
    index_name : str
        Nome desiderato per il vector index.
    """
    aws_manager = AWSClientManager()
    config_manager = ConfigManager(schema_file_path='config/domain_schema.json')
    
    aoss_client = aws_manager.get_boto3_client('opensearchserverless')
    sts_client = aws_manager.get_boto3_client('sts')
    
    identity = sts_client.get_caller_identity()
    account_id = identity['Account']
    user_arn = identity['Arn']
    
    # Costruiamo il Role ARN di default usato da Bedrock (o passato come env/param)
    bedrock_role_arn = f"arn:aws:iam::{account_id}:role/AmazonBedrockExecutionRoleForKnowledgeBase_domain"
    
    print(f"User ARN: {user_arn}")
    print(f"Bedrock Role ARN: {bedrock_role_arn}")
    
    # 1. Encryption Policy
    enc_policy_name = f"{collection_name}-enc"
    try:
        aoss_client.create_security_policy(
            name=enc_policy_name,
            type='encryption',
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]}],
                "AWSOwnedKey": True
            })
        )
        print(f"Encryption policy '{enc_policy_name}' created.")
    except Exception as e:
        if 'ConflictException' in str(e):
            print(f"Encryption policy '{enc_policy_name}' already exists.")
        else:
            raise e

    # 2. Network Policy
    net_policy_name = f"{collection_name}-net"
    try:
        aoss_client.create_security_policy(
            name=net_policy_name,
            type='network',
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]},
                    {"ResourceType": "dashboard", "Resource": [f"collection/{collection_name}"]}
                ],
                "AllowFromPublic": True
            }])
        )
        print(f"Network policy '{net_policy_name}' created.")
    except Exception as e:
        if 'ConflictException' in str(e):
            print(f"Network policy '{net_policy_name}' already exists.")
        else:
            raise e

    # 3. Data Access Policy
    access_policy_name = f"{collection_name}-access"
    try:
        aoss_client.create_access_policy(
            name=access_policy_name,
            type='data',
            policy=json.dumps([{
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{collection_name}"],
                        "Permission": ["aoss:CreateCollectionItems", "aoss:DeleteCollectionItems", "aoss:UpdateCollectionItems", "aoss:DescribeCollectionItems"]
                    },
                    {
                        "ResourceType": "index",
                        "Resource": [f"index/{collection_name}/*"],
                        "Permission": ["aoss:CreateIndex", "aoss:DeleteIndex", "aoss:UpdateIndex", "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument"]
                    }
                ],
                "Principal": [user_arn, bedrock_role_arn]
            }])
        )
        print(f"Data access policy '{access_policy_name}' created.")
    except Exception as e:
        if 'ConflictException' in str(e):
            print(f"Data access policy '{access_policy_name}' already exists.")
        else:
            raise e

    # 4. Create Collection
    collection_endpoint = None
    try:
        response = aoss_client.create_collection(
            name=collection_name,
            type='VECTORSEARCH',
            description='Enterprise vector collection'
        )
        print(f"Collection '{collection_name}' creation initiated.")
    except Exception as e:
        if 'ConflictException' in str(e):
            print(f"Collection '{collection_name}' already exists.")
        else:
            raise e

    # 5. Wait for ACTIVE state
    print("Waiting for collection to become ACTIVE...")
    while True:
        desc = aoss_client.batch_get_collection(names=[collection_name])
        details = desc['collectionDetails'][0]
        status = details['status']
        if status == 'ACTIVE':
            collection_endpoint = details['collectionEndpoint']
            break
        elif status == 'FAILED':
            print("Collection creation failed!")
            sys.exit(1)
        time.sleep(10)

    print(f"Collection is ACTIVE. Endpoint: {collection_endpoint}")
    print("Waiting 15 seconds for IAM policy propagation...")
    time.sleep(15)

    # 6. Create Vector Index based on Schema
    opensearch_client = aws_manager.get_opensearch_client(collection_endpoint)
    
    properties_dict = {
        "id": {"type": "keyword"},
        "vector": {
            "type": "knn_vector",
            "dimension": 1024,
            "method": {"name": "hnsw", "engine": "faiss", "space_type": "l2"}
        },
        "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text"},
        "AMAZON_BEDROCK_METADATA": {"type": "text"}
    }
    
    # Map domain schema fields to OpenSearch types
    for field in config_manager.get_metadata_fields():
        field_name = field['name']
        field_type = field['type']
        if field_type == 'float':
            properties_dict[field_name] = {"type": "float"}
        elif field_type == 'integer':
            properties_dict[field_name] = {"type": "integer"}
        else:
            properties_dict[field_name] = {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}
            }
            
    index_body = {
        "settings": {"index.knn": True},
        "mappings": {"properties": properties_dict}
    }

    try:
        if opensearch_client.indices.exists(index=index_name):
            print(f"Index '{index_name}' exists. Deleting to recreate mappings...")
            opensearch_client.indices.delete(index=index_name)
            time.sleep(2)
        print(f"Creating index '{index_name}'...")
        opensearch_client.indices.create(index=index_name, body=index_body)
        print("Index created successfully!")
    except Exception as e:
        print(f"Error creating index: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="domain-collection", help="AOSS Collection name")
    parser.add_argument("--index", default="domain-index", help="AOSS Index name")
    args = parser.parse_args()
    create_aoss_resources(args.collection, args.index)
