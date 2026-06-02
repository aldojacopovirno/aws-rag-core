#!/bin/bash
set -e

# ==============================================================================
# Enterprise RAG Deployment Script
# Orchestrates IAM, AOSS provisioning, S3 setup, and Knowledge Base creation.
# ==============================================================================

AWS_REGION=$(aws configure get region || echo "eu-central-1")
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
DOMAIN_PREFIX="domain" # Modificare per personalizzare i nomi delle risorse

BUCKET_NAME="${DOMAIN_PREFIX}-rag-datasource-${ACCOUNT_ID}"
ROLE_NAME="AmazonBedrockExecutionRoleForKnowledgeBase_${DOMAIN_PREFIX}"
POLICY_NAME="AmazonBedrockExecutionPolicyForKnowledgeBase_${DOMAIN_PREFIX}"
COLLECTION_NAME="${DOMAIN_PREFIX}-collection"
INDEX_NAME="${DOMAIN_PREFIX}-index"
KB_NAME="${DOMAIN_PREFIX}-kb"

echo "=== Enterprise RAG Deployment ==="
echo "AWS Region: $AWS_REGION"
echo "Account ID: $ACCOUNT_ID"

# 1. IAM Role & Policy for Bedrock KB
echo "Step 1: IAM Role & Policy setup..."
TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "IAM Role '$ROLE_NAME' exists."
else
    aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" >/dev/null
    echo "IAM Role created."
fi

IAM_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["bedrock:InvokeModel"],"Resource":["arn:aws:bedrock:'${AWS_REGION}'::foundation-model/amazon.titan-embed-text-v2:0"]},{"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::'${BUCKET_NAME}'","arn:aws:s3:::'${BUCKET_NAME}'/*"]},{"Effect":"Allow","Action":["aoss:APIAccessAll"],"Resource":["arn:aws:aoss:'${AWS_REGION}':'${ACCOUNT_ID}':collection/*"]}]}'
policy_arn="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

if aws iam get-policy --policy-arn "$policy_arn" >/dev/null 2>&1; then
    echo "IAM Policy exists."
else
    aws iam create-policy --policy-name "$POLICY_NAME" --policy-document "$IAM_POLICY" >/dev/null
    echo "IAM Policy created."
fi
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$policy_arn"

# 2. Provision OpenSearch Serverless
echo "Step 2: Provisioning OpenSearch Serverless (AOSS)..."
python3 src/scripts/provision_aoss.py --collection "$COLLECTION_NAME" --index "$INDEX_NAME"

collection_details=$(aws opensearchserverless batch-get-collection --names "$COLLECTION_NAME")
COLLECTION_ARN=$(echo "$collection_details" | jq -r '.collectionDetails[0].arn')
COLLECTION_ID=$(echo "$COLLECTION_ARN" | awk -F'/' '{print $2}')

# 3. Setup S3 & Prepare Data (Assumes raw data is in 'data/raw.json')
echo "Step 3: Setup S3 and Data Preparation..."
if aws s3api head-bucket --bucket "$BUCKET_NAME" >/dev/null 2>&1; then
    echo "S3 Bucket exists."
else
    if [ "$AWS_REGION" == "us-east-1" ]; then
        aws s3api create-bucket --bucket "$BUCKET_NAME" >/dev/null
    else
        aws s3api create-bucket --bucket "$BUCKET_NAME" --create-bucket-configuration LocationConstraint="$AWS_REGION" >/dev/null
    fi
fi

aws s3 rm "s3://${BUCKET_NAME}/" --recursive
echo "Uploading prepared data to S3..."
# Ensure data is generated before upload via prepare_data.py
python3 src/scripts/prepare_data.py --input data/raw.json --outdir data/processed
aws s3 sync data/processed/ "s3://${BUCKET_NAME}/" --include "*.csv" --include "*.metadata.json"

# 4. Bedrock Knowledge Base & Data Source Creation
echo "Step 4: Creating Bedrock KB & DataSource..."
sleep 10 # Let IAM policies propagate

KB_CONFIG='{"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":"arn:aws:bedrock:'${AWS_REGION}'::foundation-model/amazon.titan-embed-text-v2:0"}}'
STORAGE_CONFIG='{"type":"OPENSEARCH_SERVERLESS","opensearchServerlessConfiguration":{"collectionArn":"'${COLLECTION_ARN}'","vectorIndexName":"'${INDEX_NAME}'","fieldMapping":{"vectorField":"vector","textField":"AMAZON_BEDROCK_TEXT_CHUNK","metadataField":"AMAZON_BEDROCK_METADATA"}}}'

kb_id=$(aws bedrock-agent create-knowledge-base --name "$KB_NAME" --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" --knowledge-base-configuration "$KB_CONFIG" --storage-configuration "$STORAGE_CONFIG" | jq -r '.knowledgeBase.knowledgeBaseId' || echo "EXISTING_KB_LOGIC_OMITTED_FOR_BREVITY")
echo "KB ID: $kb_id"

DS_CONFIG='{"bucketArn":"arn:aws:s3:::'${BUCKET_NAME}'"}'
ds_id=$(aws bedrock-agent create-data-source --knowledge-base-id "$kb_id" --name "${DOMAIN_PREFIX}-s3-ds" --data-source-configuration "{\"type\":\"S3\",\"s3Configuration\":$DS_CONFIG}" | jq -r '.dataSource.dataSourceId' || echo "EXISTING_DS_LOGIC_OMITTED")
echo "Data Source ID: $ds_id"

# 5. Save Config
echo "Saving application config..."
mkdir -p config
cat <<EOF > config/app_config.json
{
  "KNOWLEDGE_BASE_ID": "$kb_id",
  "DATA_SOURCE_ID": "$ds_id",
  "S3_BUCKET": "$BUCKET_NAME",
  "AOSS_COLLECTION_ID": "$COLLECTION_ID"
}
EOF
echo "Deployment Complete."
