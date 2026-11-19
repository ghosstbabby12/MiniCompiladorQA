"""Detector de DRIFT (deriva de configuración) del bucket de reportes.

Drift = la infraestructura REAL ya no coincide con la DECLARADA. Pasa cuando
alguien cambia algo "a mano" en la consola, con un script suelto o en una
emergencia, y no actualiza el código. El código deja de ser la verdad.

Este módulo lee el estado real con boto3 y lo compara con
``infra/estado_deseado.json``. Es la misma idea que
``terraform plan -detailed-exitcode`` (exit 2 = hay cambios), pero escrito en
Python para que la prueba sea explícita y explicable.

Uso:
    AWS_ENDPOINT_URL=http://localhost:4566 python infra/scripts/drift.py
    → exit 0 sin drift · exit 2 con drift (lista las diferencias)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

RUTA_ESTADO_DESEADO = Path(__file__).resolve().parents[1] / "estado_deseado.json"
SALIDA_SIN_DRIFT, SALIDA_CON_DRIFT = 0, 2


def cargar_estado_deseado(ruta: Path = RUTA_ESTADO_DESEADO) -> dict[str, Any]:
    return json.loads(ruta.read_text(encoding="utf-8"))


def crear_cliente(region: str) -> Any:
    """Cliente S3 para LocalStack (path-style) o AWS (si no hay AWS_ENDPOINT_URL)."""
    import os

    import boto3
    from botocore.config import Config

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    return boto3.client("s3", region_name=region, config=Config(s3={"addressing_style": "path"}))


def _o_none(llamada, *codigos_ausente: str) -> Any:
    """Ejecuta una lectura de boto3; si la configuración no existe, devuelve None."""
    try:
        return llamada()
    except ClientError as error:
        if error.response["Error"]["Code"] in codigos_ausente:
            return None
        raise


def existe_bucket(cliente: Any, bucket: str) -> bool:
    return _o_none(lambda: cliente.head_bucket(Bucket=bucket), "404", "NoSuchBucket") is not None


def leer_estado_real(cliente: Any, bucket: str) -> dict[str, Any] | None:
    """Estado real del bucket con las MISMAS claves que estado_deseado.json."""
    if not existe_bucket(cliente, bucket):
        return None

    versionado = cliente.get_bucket_versioning(Bucket=bucket).get("Status", "Disabled")

    cifrado = _o_none(
        lambda: cliente.get_bucket_encryption(Bucket=bucket),
        "ServerSideEncryptionConfigurationNotFoundError",
    )
    # Tras borrar el cifrado, S3 puede responder sin la clave "Rules": no asumir.
    reglas = (cifrado or {}).get("ServerSideEncryptionConfiguration", {}).get("Rules") or [{}]
    algoritmo = reglas[0].get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")

    bloqueo = _o_none(
        lambda: cliente.get_public_access_block(Bucket=bucket),
        "NoSuchPublicAccessBlockConfiguration",
    )
    bloqueo_total = bool(bloqueo) and all(bloqueo["PublicAccessBlockConfiguration"].values())

    ciclo = _o_none(
        lambda: cliente.get_bucket_lifecycle_configuration(Bucket=bucket),
        "NoSuchLifecycleConfiguration",
    )
    dias = next(
        (
            regla["Expiration"]["Days"]
            for regla in (ciclo or {}).get("Rules", [])
            if regla.get("Status") == "Enabled" and "Days" in regla.get("Expiration", {})
        ),
        None,
    )

    etiquetas = _o_none(lambda: cliente.get_bucket_tagging(Bucket=bucket), "NoSuchTagSet")
    return {
        "bucket": bucket,
        "versionado": versionado,
        "cifrado": algoritmo,
        "bloqueo_acceso_publico": bloqueo_total,
        "dias_retencion_reportes": dias,
        "etiquetas": {e["Key"]: e["Value"] for e in (etiquetas or {}).get("TagSet", [])},
    }


def diferencias(deseado: dict[str, Any], real: dict[str, Any] | None) -> list[str]:
    """Lista legible de diferencias; vacía = sin drift."""
    if real is None:
        return [f"el bucket '{deseado['bucket']}' no existe"]
    return [
        f"{clave}: declarado={deseado[clave]!r} real={real[clave]!r}"
        for clave in real
        if deseado[clave] != real[clave]
    ]


def main() -> int:
    deseado = cargar_estado_deseado()
    cliente = crear_cliente(deseado["region"])
    cambios = diferencias(deseado, leer_estado_real(cliente, deseado["bucket"]))
    if not cambios:
        print(f"✔ Sin drift: s3://{deseado['bucket']} coincide con estado_deseado.json")
        return SALIDA_SIN_DRIFT
    print(f"✘ DRIFT detectado en s3://{deseado['bucket']}:")
    for cambio in cambios:
        print(f"  - {cambio}")
    print("Corrige con: terraform apply (vuelve al estado declarado).")
    return SALIDA_CON_DRIFT


if __name__ == "__main__":
    sys.exit(main())
