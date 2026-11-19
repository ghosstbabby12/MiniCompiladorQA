#!/usr/bin/env sh
# Ejecuta Terraform dentro de Docker contra el LocalStack de docker compose
# (no hace falta instalar Terraform en la máquina).
#
#   ./infra/tf.sh plan -detailed-exitcode   # exit 0 = sin cambios, 2 = drift
#   ./infra/tf.sh apply -auto-approve       # vuelve al estado declarado
set -eu

RAIZ=$(cd "$(dirname "$0")/.." && pwd)
RED=${RED_COMPOSE:-minicompiladorqa_default}

exec docker run --rm \
  --network "$RED" \
  -v "$RAIZ/infra:/infra" \
  -w /infra/terraform \
  hashicorp/terraform:1.9.8 \
  "$@" -input=false -var endpoint_localstack=http://localstack:4566
