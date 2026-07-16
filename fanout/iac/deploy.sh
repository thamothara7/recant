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
BUILD=fanout/iac/build

# --- secret to SSM -----------------------------------------------------------
# The Lambda URL swaps the local CA path for the one packaged into the zip
# (package.sh ships the cluster CA at /var/task/root.crt); verify-full stays.
DATABASE_URL_CLOUD=$(grep '^DATABASE_URL_CLOUD=' .env | cut -d= -f2-)
[ -n "$DATABASE_URL_CLOUD" ] || { echo "DATABASE_URL_CLOUD missing from .env" >&2; exit 1; }
LAMBDA_URL="${DATABASE_URL_CLOUD}&sslrootcert=/var/task/root.crt"
aws ssm put-parameter --region "$REGION" --name "$DB_PARAM" \
  --type SecureString --value "$LAMBDA_URL" --overwrite >/dev/null
echo "ssm: $DB_PARAM"

# --- event bus ----------------------------------------------------------------
aws events create-event-bus --region "$REGION" --name "$BUS" 2>/dev/null \
  && echo "bus: created $BUS" || echo "bus: $BUS exists"

# --- roles ---------------------------------------------------------------------
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

ensure_role() { # name policy-json
  aws iam create-role --role-name "$1" --assume-role-policy-document "$TRUST" >/dev/null 2>&1 \
    && echo "role: created $1" || echo "role: $1 exists"
  aws iam attach-role-policy --role-name "$1" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null 2>&1 || true
  aws iam put-role-policy --role-name "$1" --policy-name "$1-inline" --policy-document "$2"
}

ensure_role recant-fanout-receiver "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"events:PutEvents\",\"Resource\":\"arn:aws:events:$REGION:$ACCOUNT:event-bus/$BUS\"}]}"
ensure_role recant-fanout-consumer "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ssm:GetParameter\",\"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter$DB_PARAM\"}]}"
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
  recant-fanout-receiver "{\"Variables\":{\"RECANT_EVENT_BUS\":\"$BUS\"}}"
ensure_fn recant-fanout-consumer "$BUILD/consumer.zip" fanout.consumer_entry.handler \
  recant-fanout-consumer "{\"Variables\":{\"RECANT_DB_PARAM\":\"$DB_PARAM\",\"RECANT_CONSUMER\":\"cloud-evictor\"}}"

# --- receiver function URL (the changefeed webhook target) ----------------------
# auth NONE: CockroachDB's webhook sink cannot SigV4-sign. The URL itself is the
# only credential (128-bit random host). Hardening path: API Gateway + client
# certs, out of hackathon scope, noted in the README.
aws lambda create-function-url-config --region "$REGION" \
  --function-name recant-fanout-receiver --auth-type NONE >/dev/null 2>&1 || true
aws lambda add-permission --region "$REGION" --function-name recant-fanout-receiver \
  --statement-id url-invoke --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
URL=$(aws lambda get-function-url-config --region "$REGION" \
  --function-name recant-fanout-receiver --query FunctionUrl --output text)

# --- rule: bus -> consumer -------------------------------------------------------
aws events put-rule --region "$REGION" --name recant-fanout --event-bus-name "$BUS" \
  --event-pattern '{"source":["recant.fanout"],"detail-type":["recant"]}' >/dev/null
aws events put-targets --region "$REGION" --rule recant-fanout --event-bus-name "$BUS" \
  --targets "Id"="consumer","Arn"="arn:aws:lambda:$REGION:$ACCOUNT:function:recant-fanout-consumer" >/dev/null
aws lambda add-permission --region "$REGION" --function-name recant-fanout-consumer \
  --statement-id eventbridge-invoke --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$REGION:$ACCOUNT:rule/$BUS/recant-fanout" >/dev/null 2>&1 || true

echo
echo "deployed. changefeed webhook target:"
echo "  $URL"
echo "create the changefeed on the cloud cluster with:"
echo "  CREATE CHANGEFEED FOR TABLE memory_events INTO 'webhook-${URL%/}' WITH updated;"
