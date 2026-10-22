#!/usr/bin/env bash
# Creates the local-only evidence bucket and incident queues in the Guardian MiniStack (port 4570).
# Ignores shared AWS config/credentials/profiles and uses dummy credentials only.
set -euo pipefail

ENDPOINT="${MINISTACK_ENDPOINT:-http://localhost:4570}"
case "${ENDPOINT}" in
  http://localhost:4570|http://127.0.0.1:4570) ;;
  *) echo "Refusing endpoint other than local port 4570: ${ENDPOINT}" >&2; exit 1 ;;
esac

unset AWS_PROFILE AWS_SESSION_TOKEN AWS_ENDPOINT_URL
export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL="${ENDPOINT}"

curl -fsS "${ENDPOINT}/_ministack/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ministack", d["version"], "auth:", d["auth"])'
aws s3api create-bucket --bucket aiops-guardian-evidence >/dev/null
aws sqs create-queue --queue-name aiops-guardian-incidents-dlq >/dev/null
aws sqs create-queue --queue-name aiops-guardian-incidents >/dev/null
aws s3api list-buckets --query 'Buckets[].Name' --output text
aws sqs list-queues --query 'QueueUrls' --output text
