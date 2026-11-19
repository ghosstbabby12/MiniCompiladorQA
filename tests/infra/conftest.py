"""Pruebas de infraestructura (drift) contra LocalStack.

Las pruebas marcadas ``localstack`` necesitan el bucket creado por Terraform:

    docker compose -f docker-compose.yml -f docker-compose.s3.yml up -d --wait api
    LOCALSTACK_URL=http://localhost:4566 pytest tests/infra -o addopts=""

Sin ``LOCALSTACK_URL`` esas pruebas se omiten; las de lógica pura corren siempre.
"""

import os
import sys
from pathlib import Path

import pytest

# Los scripts de infra no son un paquete instalable: se agregan al path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "scripts"))


@pytest.fixture(scope="session")
def s3():
    url = os.environ.get("LOCALSTACK_URL")
    if not url:
        pytest.skip("LOCALSTACK_URL no definida: se omiten las pruebas contra LocalStack")
    os.environ["AWS_ENDPOINT_URL"] = url
    from drift import crear_cliente

    return crear_cliente("us-east-1")
