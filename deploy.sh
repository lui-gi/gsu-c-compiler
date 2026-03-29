#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy the gcc-sandbox Lambda function.
#
# Prerequisites:
#   - AWS CLI configured (aws configure, or IAM instance profile on EC2)
#   - Docker installed and running
#   - IAM permissions: ecr:*, lambda:CreateFunction/UpdateFunctionCode/
#                      UpdateFunctionConfiguration/PutFunctionConcurrency,
#                      iam:CreateRole/AttachRolePolicy/PassRole
#
# Usage:
#   ./deploy.sh
#   AWS_REGION=us-west-2 ./deploy.sh
#   ./deploy.sh --memory-mb 512 --timeout-s 30

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-gcc-sandbox}"
MEMORY_MB="${LAMBDA_MEMORY_MB:-256}"
TIMEOUT_S="${LAMBDA_TIMEOUT_S:-30}"    # must exceed COMPILE_TIMEOUT_S + EXEC_TIMEOUT_S

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --region)     REGION="$2";     shift 2 ;;
        --memory-mb)  MEMORY_MB="$2";  shift 2 ;;
        --timeout-s)  TIMEOUT_S="$2";  shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Derive ECR URI ────────────────────────────────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="gcc-sandbox"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
IMAGE_TAG="latest"
FULL_IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"

echo "==> Account:  $ACCOUNT_ID"
echo "==> Region:   $REGION"
echo "==> ECR URI:  $FULL_IMAGE_URI"
echo "==> Function: $FUNCTION_NAME"
echo "==> Memory:   ${MEMORY_MB} MB  Timeout: ${TIMEOUT_S}s"
echo ""

# ── 1. Ensure ECR repository exists ──────────────────────────────────────────
echo "==> Ensuring ECR repository..."
aws ecr describe-repositories --repository-names "$ECR_REPO" \
    --region "$REGION" > /dev/null 2>&1 || \
aws ecr create-repository \
    --repository-name "$ECR_REPO" \
    --region "$REGION" \
    --image-scanning-configuration scanOnPush=true \
    --output table

# ── 2. Authenticate Docker to ECR ────────────────────────────────────────────
echo "==> Logging Docker into ECR..."
aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin \
        "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# ── 3. Build Lambda container image ──────────────────────────────────────────
echo "==> Building Lambda image..."
docker build \
    --platform linux/amd64 \
    -t "${ECR_REPO}:${IMAGE_TAG}" \
    ./lambda

# ── 4. Tag and push to ECR ───────────────────────────────────────────────────
echo "==> Pushing to ECR..."
docker tag "${ECR_REPO}:${IMAGE_TAG}" "$FULL_IMAGE_URI"
docker push "$FULL_IMAGE_URI"

DIGEST=$(aws ecr describe-images \
    --repository-name "$ECR_REPO" \
    --region "$REGION" \
    --image-ids imageTag="$IMAGE_TAG" \
    --query 'imageDetails[0].imageDigest' \
    --output text)
PINNED_URI="${ECR_URI}@${DIGEST}"
echo "==> Image digest: $DIGEST"

# ── 5. Ensure IAM execution role ─────────────────────────────────────────────
ROLE_NAME="${FUNCTION_NAME}-exec-role"
echo "==> Ensuring IAM role: $ROLE_NAME"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
    --query 'Role.Arn' --output text 2>/dev/null || \
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --query 'Role.Arn' --output text)

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    2>/dev/null || true

echo "==> Role ARN: $ROLE_ARN"
# IAM is eventually consistent; pause briefly after role creation.
sleep 5

# ── 6. Create or update the Lambda function ───────────────────────────────────
echo "==> Deploying Lambda function..."
if aws lambda get-function --function-name "$FUNCTION_NAME" \
        --region "$REGION" > /dev/null 2>&1; then
    echo "    Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --image-uri "$PINNED_URI" \
        --output table
    aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --memory-size "$MEMORY_MB" \
        --timeout "$TIMEOUT_S" \
        --output table
else
    echo "    Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --package-type Image \
        --code "ImageUri=${PINNED_URI}" \
        --role "$ROLE_ARN" \
        --memory-size "$MEMORY_MB" \
        --timeout "$TIMEOUT_S" \
        --architectures x86_64 \
        --output table
    aws lambda wait function-active \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"
fi

# ── 7. Cap concurrency to limit blast radius from network-capable student code ─
echo "==> Setting reserved concurrency to 10..."
aws lambda put-function-concurrency \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --reserved-concurrent-executions 10 \
    --output table

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
echo "==> Running smoke test..."
HELLO_CODE='#include <stdio.h>\nint main(void) { printf("hello from lambda\\n"); return 0; }'
PAYLOAD=$(python3 -c "
import json, sys
code = '$HELLO_CODE'.replace('\\\\n', '\n')
print(json.dumps({'code': code}))
")

OUTFILE=$(mktemp)
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    "$OUTFILE" > /dev/null

echo "==> Smoke test response:"
cat "$OUTFILE"
rm "$OUTFILE"

echo ""
echo "==> Deploy complete."
echo "    Add to your .env:"
echo "    LAMBDA_FUNCTION_NAME=$FUNCTION_NAME"
echo "    AWS_REGION=$REGION"
