"""Persistencia de reportes en S3 (LocalStack en desarrollo, AWS en producción).

Diseño (inyección de dependencias):
    La API no sabe si guarda en S3, en memoria o en ningún lado: recibe un
    objeto que cumple el protocolo ``Almacenamiento``. Así:
      * sin configurar nada, se usa ``AlmacenamientoNulo`` (no guarda) y el
        compilador sigue funcionando sin AWS ni boto3;
      * en las pruebas unitarias se inyecta un cliente de S3 "stubbeado"
        (``botocore.stub.Stubber``): sin red, rápido y determinista;
      * en docker compose (perfil S3) se usa LocalStack, un S3 falso local.

Configuración por variables de entorno (12-factor: config fuera del código):
    MINICOMPILADOR_BUCKET   nombre del bucket. Si no existe → no se guarda.
    AWS_ENDPOINT_URL        p. ej. http://localstack:4566 (boto3 la lee solo).
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION
                            credenciales estándar de AWS (en LocalStack: "test").

Si S3 falla, el usuario igual recibe su reporte: guardar es un efecto
secundario y NO debe tumbar la compilación (degradación elegante).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

VARIABLE_BUCKET = "MINICOMPILADOR_BUCKET"
PREFIJO_CLAVES = "reportes"

registro = logging.getLogger(__name__)


class ErrorAlmacenamiento(Exception):
    """No se pudo guardar el reporte (red, permisos, bucket inexistente...)."""


class Almacenamiento(Protocol):
    """Lo único que la API necesita saber de un almacenamiento."""

    def guardar(self, reporte: dict[str, Any]) -> str | None:
        """Guarda el reporte y devuelve su identificador (``None`` si no guarda)."""
        ...  # pragma: no cover - es solo la firma del protocolo


class AlmacenamientoNulo:
    """Patrón *Null Object*: cumple el protocolo sin hacer nada."""

    def guardar(self, reporte: dict[str, Any]) -> None:
        return None


class AlmacenamientoS3:
    """Guarda cada reporte como un objeto JSON en un bucket de S3.

    Clave: ``reportes/AAAA/MM/DD/<uuid>.json``. Particionar por fecha permite
    listar o expirar (regla de ciclo de vida) los reportes de un día concreto.
    """

    def __init__(
        self,
        bucket: str,
        cliente: Any,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
        generar_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        # reloj y generar_id se inyectan para que las pruebas conozcan la clave exacta.
        self.bucket = bucket
        self.cliente = cliente
        self._reloj = reloj
        self._generar_id = generar_id

    def clave_para(self, momento: datetime, identificador: str) -> str:
        return f"{PREFIJO_CLAVES}/{momento:%Y/%m/%d}/{identificador}.json"

    def guardar(self, reporte: dict[str, Any]) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        clave = self.clave_para(self._reloj(), self._generar_id())
        cuerpo = json.dumps(reporte, ensure_ascii=False).encode("utf-8")
        try:
            self.cliente.put_object(
                Bucket=self.bucket,
                Key=clave,
                Body=cuerpo,
                ContentType="application/json; charset=utf-8",
                # Metadatos: permiten filtrar sin descargar el JSON completo.
                Metadata={
                    "fase-alcanzada": str(reporte.get("fase_alcanzada")),
                    "exito": str(reporte.get("exito")).lower(),
                },
            )
        # ClientError: S3 respondió con error (bucket inexistente, permisos).
        # BotoCoreError: ni siquiera hubo respuesta (red, endpoint, credenciales).
        except (ClientError, BotoCoreError) as error:
            raise ErrorAlmacenamiento(
                f"No se pudo guardar en s3://{self.bucket}: {error}"
            ) from error
        return clave


def crear_cliente_s3(entorno: Mapping[str, str]) -> Any:
    """Cliente de boto3. Importación diferida: boto3 solo es necesario si hay bucket."""
    import boto3
    from botocore.config import Config

    # Con un endpoint propio (LocalStack) se usan URLs "path-style"
    # (http://host:4566/bucket/clave): el estilo virtual (bucket.host) requiere DNS.
    estilo = "path" if entorno.get("AWS_ENDPOINT_URL") else "auto"
    return boto3.client(
        "s3",
        config=Config(
            s3={"addressing_style": estilo},
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=2,
            read_timeout=5,
        ),
    )


def crear_desde_entorno(
    entorno: Mapping[str, str] | None = None,
    fabrica_cliente: Callable[[Mapping[str, str]], Any] = crear_cliente_s3,
) -> AlmacenamientoNulo | AlmacenamientoS3:
    """Elige la implementación según las variables de entorno."""
    entorno = os.environ if entorno is None else entorno
    bucket = entorno.get(VARIABLE_BUCKET, "").strip()
    if not bucket:
        registro.info("Sin %s: los reportes no se guardan.", VARIABLE_BUCKET)
        return AlmacenamientoNulo()
    registro.info("Los reportes se guardarán en s3://%s", bucket)
    return AlmacenamientoS3(bucket, fabrica_cliente(entorno))
