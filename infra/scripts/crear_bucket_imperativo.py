"""Crear el bucket de reportes de forma IMPERATIVA (boto3), para contrastar con Terraform.

IMPERATIVO (este script)              DECLARATIVO (infra/terraform)
--------------------------------      ----------------------------------------
Dice los PASOS: crea, luego           Dice el RESULTADO: "debe existir un
configura versionado, luego...        bucket con versionado, cifrado..."
El ORDEN lo decide el programador.    Terraform calcula el orden (grafo de
                                      dependencias).
Sin memoria: no sabe qué creó         Guarda un ESTADO (terraform.tfstate) y
antes. Hay que programar a mano       compara: si ya está igual, no hace nada
"si ya existe, no lo crees".          (idempotente por diseño).
Si borras una línea (p. ej. el        Si borras un recurso del código, el
cifrado), el bucket SIGUE cifrado:    plan propone ELIMINARLO: el código
el script no deshace nada.            sigue siendo la verdad.
No hay "plan" previo: ejecuta y ya.   ``terraform plan`` muestra qué cambiará
                                      ANTES de tocar nada.

¿Cuándo usar boto3 entonces? Para tareas operativas puntuales (subir un
archivo, rotar algo, consultas, pruebas de drift), no para definir la
infraestructura que debe perdurar.

Uso (con LocalStack corriendo):
    AWS_ENDPOINT_URL=http://localhost:4566 python infra/scripts/crear_bucket_imperativo.py
"""

from __future__ import annotations

import sys
from typing import Any

from drift import (
    cargar_estado_deseado,
    crear_cliente,
    diferencias,
    existe_bucket,
    leer_estado_real,
)


def crear_o_actualizar(cliente: Any, deseado: dict[str, Any]) -> list[str]:
    """Ejecuta los pasos uno por uno. Devuelve la bitácora de lo que hizo."""
    bucket = deseado["bucket"]
    bitacora: list[str] = []

    # Paso 1: crear el bucket. La idempotencia hay que programarla A MANO.
    # Ojo: NO basta con capturar el error de create_bucket, porque en us-east-1
    # crear un bucket propio que ya existe responde 200 (compatibilidad
    # histórica de AWS). Por eso se pregunta primero. Terraform lo resuelve
    # solo comparando contra su estado.
    if existe_bucket(cliente, bucket):
        bitacora.append(f"s3://{bucket} ya existía (se continúa)")
    else:
        cliente.create_bucket(Bucket=bucket)
        bitacora.append(f"creado s3://{bucket}")

    # Paso 2..N: cada aspecto es una llamada distinta, en el orden que yo elijo.
    # (El ciclo de vida va DESPUÉS del versionado: ese orden lo sé yo, no la herramienta.)
    cliente.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": deseado["versionado"]}
    )
    bitacora.append(f"versionado = {deseado['versionado']}")

    cliente.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": deseado["cifrado"]}}]
        },
    )
    bitacora.append(f"cifrado = {deseado['cifrado']}")

    bloquear = deseado["bloqueo_acceso_publico"]
    cliente.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": bloquear,
            "IgnorePublicAcls": bloquear,
            "BlockPublicPolicy": bloquear,
            "RestrictPublicBuckets": bloquear,
        },
    )
    bitacora.append(f"bloqueo de acceso público = {bloquear}")

    dias = deseado["dias_retencion_reportes"]
    cliente.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expirar-reportes",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "reportes/"},
                    "Expiration": {"Days": dias},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": dias},
                }
            ]
        },
    )
    bitacora.append(f"retención = {dias} días")

    cliente.put_bucket_tagging(
        Bucket=bucket,
        Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in deseado["etiquetas"].items()]},
    )
    bitacora.append(f"etiquetas = {deseado['etiquetas']}")
    return bitacora


def main() -> int:
    deseado = cargar_estado_deseado()
    cliente = crear_cliente(deseado["region"])
    for linea in crear_o_actualizar(cliente, deseado):
        print(f"· {linea}")
    # Verificación final: ¿quedó como lo declarado? (Terraform lo hace solo.)
    pendientes = diferencias(deseado, leer_estado_real(cliente, deseado["bucket"]))
    print("✔ Coincide con estado_deseado.json" if not pendientes else f"✘ {pendientes}")
    return 0 if not pendientes else 1


if __name__ == "__main__":
    sys.exit(main())
