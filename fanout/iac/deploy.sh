#!/usr/bin/env bash
# Deploy the W3 cloud fanout leg: EventBridge bus + receiver Lambda (function
# URL for the CockroachDB Cloud changefeed webhook) + consumer Lambda (applies
# evictions on the cloud cluster). Idempotent: create-or-update throughout.
#
# Requires: aws CLI authed to the target account, zips from package.sh, and
# DATABASE_URL_CLOUD in the repo .env (pushed to SSM as a SecureString; the
# secret never lands in Lambda env or git).
#
# Usage: bash fanout/iac/deploy.sh   (from the repo root)
set -euo pipefail

cd "$(dirname "$0")/../.."
REGION=${AWS_REGION:-us-east-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUS=recant
DB_PARAM=/recant/database_url_cloud
WEBHOOK_AUTH_PARAM=/recant/fanout_webhook_auth
BUILD=fanout/iac/build
MANIFEST_BUCKET=${RECANT_EVENT_MANIFEST_BUCKET:-recant-fanout-manifests-$ACCOUNT-$REGION}
DLQ=recant-fanout-dlq

for archive in "$BUILD/receiver.zip" "$BUILD/consumer.zip"; do
  [ -f "$archive" ] || { echo "$archive missing; run bash fanout/iac/package.sh" >&2; exit 1; }
done
for source in fanout/handler.py fanout/lambda_entry.py fanout/consumer_entry.py; do
  if [ "$source" -nt "$BUILD/receiver.zip" ] || [ "$source" -nt "$BUILD/consumer.zip" ]; then
    echo "fanout sources are newer than the Lambda archives; run bash fanout/iac/package.sh" >&2
    exit 1
  fi
done

# --- secret to SSM -----------------------------------------------------------
# The Lambda URL swaps the local CA path for the one packaged into the zip
# (package.sh ships the cluster CA at /var/task/root.crt); verify-full stays.
DATABASE_URL_CLOUD=$(grep '^DATABASE_URL_CLOUD=' .env | cut -d= -f2-)
[ -n "$DATABASE_URL_CLOUD" ] || { echo "DATABASE_URL_CLOUD missing from .env" >&2; exit 1; }
LAMBDA_URL="${DATABASE_URL_CLOUD}&sslrootcert=/var/task/root.crt"
aws ssm put-parameter --region "$REGION" --name "$DB_PARAM" \
  --type SecureString --value "$LAMBDA_URL" --overwrite >/dev/null
echo "ssm: $DB_PARAM"

# CockroachDB supports a Basic Authorization header for webhook changefeeds.
# Keep the header stable in SSM and expose only its SHA-256 digest to Lambda.
WEBHOOK_AUTH=$(aws ssm get-parameter --region "$REGION" --name "$WEBHOOK_AUTH_PARAM" \
  --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || true)
if [ -z "$WEBHOOK_AUTH" ]; then
  WEBHOOK_PASSWORD=$(openssl rand -hex 32)
  WEBHOOK_AUTH="Basic $(printf 'recant:%s' "$WEBHOOK_PASSWORD" | base64 | tr -d '\n')"
  aws ssm put-parameter --region "$REGION" --name "$WEBHOOK_AUTH_PARAM" \
    --type SecureString --value "$WEBHOOK_AUTH" >/dev/null
fi
WEBHOOK_AUTH_SHA256=$(printf '%s' "$WEBHOOK_AUTH" | shasum -a 256 | awk '{print $1}')
echo "ssm: $WEBHOOK_AUTH_PARAM"

# --- event bus ----------------------------------------------------------------
aws events create-event-bus --region "$REGION" --name "$BUS" 2>/dev/null \
  && echo "bus: created $BUS" || echo "bus: $BUS exists"

# Oversized EventBridge entries use encrypted S3 manifests. Versioning makes a
# retried event immutable by key from the consumer's perspective.
aws s3api head-bucket --bucket "$MANIFEST_BUCKET" 2>/dev/null || \
  aws s3api create-bucket --region "$REGION" --bucket "$MANIFEST_BUCKET" >/dev/null
aws s3api put-bucket-versioning --bucket "$MANIFEST_BUCKET" \
  --versioning-configuration Status=Enabled >/dev/null
aws s3api put-bucket-encryption --bucket "$MANIFEST_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
aws s3api put-public-access-block --bucket "$MANIFEST_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true >/dev/null
echo "manifest bucket: $MANIFEST_BUCKET"

# --- roles ---------------------------------------------------------------------
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

ensure_role() { # name policy-json
  aws iam create-role --role-name "$1" --assume-role-policy-document "$TRUST" >/dev/null 2>&1 \
    && echo "role: created $1" || echo "role: $1 exists"
  aws iam attach-role-policy --role-name "$1" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null 2>&1 || true
  aws iam put-role-policy --role-name "$1" --policy-name "$1-inline" --policy-document "$2"
}

ensure_role recant-fanout-receiver "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"events:PutEvents\",\"Resource\":\"arn:aws:events:$REGION:$ACCOUNT:event-bus/$BUS\"},{\"Effect\":\"Allow\",\"Action\":\"s3:PutObject\",\"Resource\":\"arn:aws:s3:::$MANIFEST_BUCKET/fanout/*\"}]}"
ensure_role recant-fanout-consumer "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ssm:GetParameter\",\"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter$DB_PARAM\"},{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$MANIFEST_BUCKET/fanout/*\"}]}"
sleep 8  # first-create IAM propagation

# --- lambdas -------------------------------------------------------------------
ensure_fn() { # name zip handler role env-json
  if aws lambda get-function --region "$REGION" --function-name "$1" >/dev/null 2>&1; then
    aws lambda update-function-code --region "$REGION" --function-name "$1" \
      --zip-file "fileb://$2" >/dev/null
    aws lambda wait function-updated --region "$REGION" --function-name "$1"
    aws lambda update-function-configuration --region "$REGION" --function-name "$1" \
      --environment "$5" --timeout 30 >/dev/null
    echo "fn: updated $1"
  else
    aws lambda create-function --region "$REGION" --function-name "$1" \
      --runtime python3.12 --architectures arm64 --timeout 30 --memory-size 256 \
      --zip-file "fileb://$2" --handler "$3" \
      --role "arn:aws:iam::$ACCOUNT:role/$4" \
      --environment "$5" >/dev/null
    echo "fn: created $1"
  fi
  aws lambda wait function-updated --region "$REGION" --function-name "$1"
}

ensure_fn recant-fanout-receiver "$BUILD/receiver.zip" fanout.lambda_entry.handler \
  recant-fanout-receiver "{\"Variables\":{\"RECANT_ENV\":\"production\",\"RECANT_EVENT_BUS\":\"$BUS\",\"RECANT_EVENT_MANIFEST_BUCKET\":\"$MANIFEST_BUCKET\",\"RECANT_WEBHOOK_AUTH_SHA256\":\"$WEBHOOK_AUTH_SHA256\"}}"
ensure_fn recant-fanout-consumer "$BUILD/consumer.zip" fanout.consumer_entry.handler \
  recant-fanout-consumer "{\"Variables\":{\"RECANT_ENV\":\"production\",\"RECANT_DB_PARAM\":\"$DB_PARAM\",\"RECANT_CONSUMER\":\"cloud-evictor\",\"RECANT_EVENT_MANIFEST_BUCKET\":\"$MANIFEST_BUCKET\"}}"

# --- receiver function URL (the changefeed webhook target) ----------------------
# auth NONE at the AWS edge because CockroachDB cannot SigV4-sign. The receiver
# still requires the pinned Basic header configured by webhook_auth_header.
aws lambda create-function-url-config --region "$REGION" \
  --function-name recant-fanout-receiver --auth-type NONE >/dev/null 2>&1 || true
aws lambda add-permission --region "$REGION" --function-name recant-fanout-receiver \
  --statement-id url-invoke --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
# Since October 2025, new Function URLs also require InvokeFunction. Restrict
# that public grant to requests that arrive through this Function URL.
aws lambda add-permission --region "$REGION" --function-name recant-fanout-receiver \
  --statement-id url-invoke-function --action lambda:InvokeFunction \
  --principal '*' --invoked-via-function-url >/dev/null 2>&1 || true
URL=$(aws lambda get-function-url-config --region "$REGION" \
  --function-name recant-fanout-receiver --query FunctionUrl --output text)

# --- rule: bus -> consumer -------------------------------------------------------
aws events put-rule --region "$REGION" --name recant-fanout --event-bus-name "$BUS" \
  --event-pattern '{"source":["recant.fanout"],"detail-type":["recant"]}' >/dev/null

DLQ_URL=$(aws sqs get-queue-url --region "$REGION" --queue-name "$DLQ" \
  --query QueueUrl --output text 2>/dev/null || \
  aws sqs create-queue --region "$REGION" --queue-name "$DLQ" --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --region "$REGION" --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
aws sqs set-queue-attributes --region "$REGION" --queue-url "$DLQ_URL" \
  --attributes SqsManagedSseEnabled=true >/dev/null
RULE_ARN="arn:aws:events:$REGION:$ACCOUNT:rule/$BUS/recant-fanout"
aws sqs set-queue-attributes --region "$REGION" --queue-url "$DLQ_URL" \
  --attributes "{\"Policy\":\"{\\\"Version\\\":\\\"2012-10-17\\\",\\\"Statement\\\":[{\\\"Effect\\\":\\\"Allow\\\",\\\"Principal\\\":{\\\"Service\\\":\\\"events.amazonaws.com\\\"},\\\"Action\\\":\\\"sqs:SendMessage\\\",\\\"Resource\\\":\\\"$DLQ_ARN\\\",\\\"Condition\\\":{\\\"ArnEquals\\\":{\\\"aws:SourceArn\\\":\\\"$RULE_ARN\\\"}}}]}\"}" >/dev/null
aws events put-targets --region "$REGION" --rule recant-fanout --event-bus-name "$BUS" \
  --targets "Id"="consumer","Arn"="arn:aws:lambda:$REGION:$ACCOUNT:function:recant-fanout-consumer","RetryPolicy"="{MaximumEventAgeInSeconds=86400,MaximumRetryAttempts=185}","DeadLetterConfig"="{Arn=$DLQ_ARN}" >/dev/null
aws lambda add-permission --region "$REGION" --function-name recant-fanout-consumer \
  --statement-id eventbridge-invoke --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$REGION:$ACCOUNT:rule/$BUS/recant-fanout" >/dev/null 2>&1 || true

echo
echo "deployed. changefeed webhook target:"
echo "  $URL"
echo "create the changefeed with webhook target webhook-${URL%/}"
echo "retrieve $WEBHOOK_AUTH_PARAM from SSM at execution time and pass it as webhook_auth_header"
echo "the authorization secret is intentionally never printed by this script"
