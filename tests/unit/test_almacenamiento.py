"""Pruebas del almacenamiento de reportes en S3.

Dobles de prueba usados (vocabulario del curso):
    * STUB de boto3 (``botocore.stub.Stubber``): el cliente S3 real, pero en
      vez de ir a la red responde lo que la prueba programó, y además VERIFICA
      que la llamada tenga exactamente los parámetros esperados (es un mock).
    * FAKE: ``AlmacenamientoEnMemoria`` guarda en una lista; sirve para probar
      la API sin S3.
    * DUMMY/STUB de error: ``AlmacenamientoQueFalla`` siempre lanza.
"""

import json
from datetime import UTC, datetime

import boto3
import pytest
from botocore.stub import ANY, Stubber
from fastapi.testclient import TestClient

from minicompilador.almacenamiento import (
    AlmacenamientoNulo,
    AlmacenamientoS3,
    ErrorAlmacenamiento,
    crear_cliente_s3,
    crear_desde_entorno,
)
from minicompilador.api import crear_app

BUCKET = "minicompilador-reportes"
MOMENTO_FIJO = datetime(2026, 11, 19, 10, 30, tzinfo=UTC)
REPORTE = {"exito": True, "fase_alcanzada": "simulacion", "salida": ["3"]}


@pytest.fixture
def cliente_s3():
    # Credenciales falsas: el Stubber intercepta ANTES de cualquier llamada real.
    cliente = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    with Stubber(cliente) as stub:
        yield cliente, stub
        stub.assert_no_pending_responses()  # se hicieron TODAS las llamadas esperadas


def almacenamiento_s3(cliente):
    return AlmacenamientoS3(
        BUCKET, cliente, reloj=lambda: MOMENTO_FIJO, generar_id=lambda: "abc123"
    )


# ---------------------------------------------------------------------------
# AlmacenamientoS3
# ---------------------------------------------------------------------------


def test_guardar_hace_put_object_con_clave_por_fecha(cliente_s3):
    # Arrange
    cliente, stub = cliente_s3
    clave_esperada = "reportes/2026/11/19/abc123.json"
    stub.add_response(
        "put_object",
        {"ETag": '"etag"'},
        expected_params={
            "Bucket": BUCKET,
            "Key": clave_esperada,
            "Body": json.dumps(REPORTE).encode("utf-8"),
            "ContentType": "application/json; charset=utf-8",
            "Metadata": {"fase-alcanzada": "simulacion", "exito": "true"},
        },
    )

    # Act
    clave = almacenamiento_s3(cliente).guardar(REPORTE)

    # Assert
    assert clave == clave_esperada


def test_guardar_conserva_acentos_en_utf8(cliente_s3):
    # Arrange: los mensajes de error del compilador están en español.
    cliente, stub = cliente_s3
    reporte = {"errores": [{"mensaje": "Línea inválida: ñ"}]}
    stub.add_response(
        "put_object",
        {},
        expected_params={
            "Bucket": BUCKET,
            "Key": ANY,
            "Body": '{"errores": [{"mensaje": "Línea inválida: ñ"}]}'.encode(),
            "ContentType": ANY,
            "Metadata": {"fase-alcanzada": "None", "exito": "none"},
        },
    )

    # Act / Assert (el Stubber falla si el Body no coincide)
    almacenamiento_s3(cliente).guardar(reporte)


@pytest.mark.parametrize("codigo_error", ["NoSuchBucket", "AccessDenied"])
def test_error_de_s3_se_traduce_a_error_almacenamiento(cliente_s3, codigo_error):
    # Arrange
    cliente, stub = cliente_s3
    stub.add_client_error("put_object", service_error_code=codigo_error)

    # Act / Assert
    with pytest.raises(ErrorAlmacenamiento, match=codigo_error):
        almacenamiento_s3(cliente).guardar(REPORTE)


def test_error_de_conexion_se_traduce_a_error_almacenamiento():
    # Arrange: un endpoint donde no escucha nadie (puerto 9 = "discard").
    entorno = {"AWS_ENDPOINT_URL": "http://127.0.0.1:9"}
    cliente = crear_cliente_s3(entorno)
    almacenamiento = AlmacenamientoS3(BUCKET, cliente)

    # Act / Assert
    with pytest.raises(ErrorAlmacenamiento, match="s3://minicompilador-reportes"):
        almacenamiento.guardar(REPORTE)


def test_la_clave_por_defecto_es_unica_y_con_fecha_actual():
    # Arrange
    almacenamiento = AlmacenamientoS3(BUCKET, cliente=None)

    # Act
    claves = {
        almacenamiento.clave_para(MOMENTO_FIJO, almacenamiento._generar_id()) for _ in range(50)
    }

    # Assert
    assert len(claves) == 50
    assert almacenamiento._reloj().tzinfo is UTC


# ---------------------------------------------------------------------------
# Configuración por variables de entorno
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entorno", [{}, {"MINICOMPILADOR_BUCKET": ""}, {"MINICOMPILADOR_BUCKET": "  "}]
)
def test_sin_bucket_se_usa_almacenamiento_nulo(entorno):
    # Arrange (en parámetros): variable ausente, vacía o solo espacios.
    # Act
    almacenamiento = crear_desde_entorno(entorno)

    # Assert
    assert isinstance(almacenamiento, AlmacenamientoNulo)
    assert almacenamiento.guardar(REPORTE) is None


def test_con_bucket_se_usa_s3():
    # Arrange
    entorno = {"MINICOMPILADOR_BUCKET": BUCKET}

    # Act
    almacenamiento = crear_desde_entorno(entorno, fabrica_cliente=lambda _: "cliente-falso")

    # Assert
    assert isinstance(almacenamiento, AlmacenamientoS3)
    assert almacenamiento.bucket == BUCKET
    assert almacenamiento.cliente == "cliente-falso"


def test_por_defecto_lee_las_variables_del_proceso(monkeypatch):
    # Arrange
    monkeypatch.delenv("MINICOMPILADOR_BUCKET", raising=False)

    # Act / Assert
    assert isinstance(crear_desde_entorno(), AlmacenamientoNulo)


@pytest.mark.parametrize(
    ("entorno", "estilo"),
    [
        ({"AWS_ENDPOINT_URL": "http://localstack:4566"}, "path"),  # LocalStack
        ({}, "auto"),  # AWS real
    ],
)
def test_estilo_de_direccion_segun_endpoint(entorno, estilo, monkeypatch):
    # Arrange
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    # Act
    cliente = crear_cliente_s3(entorno)

    # Assert
    assert cliente.meta.config.s3["addressing_style"] == estilo


# ---------------------------------------------------------------------------
# Integración con la API (dobles de prueba inyectados en crear_app)
# ---------------------------------------------------------------------------


class AlmacenamientoEnMemoria:
    def __init__(self):
        self.reportes = []

    def guardar(self, reporte):
        self.reportes.append(reporte)
        return f"reportes/memoria/{len(self.reportes)}.json"


class AlmacenamientoQueFalla:
    def guardar(self, reporte):
        raise ErrorAlmacenamiento("S3 caído")


def test_api_guarda_el_reporte_y_devuelve_la_clave():
    # Arrange
    fake = AlmacenamientoEnMemoria()
    cliente = TestClient(crear_app(fake))

    # Act
    respuesta = cliente.post("/compilar", json={"codigo": "print(1);"})

    # Assert
    assert respuesta.headers["X-Reporte-Clave"] == "reportes/memoria/1.json"
    assert fake.reportes == [respuesta.json()]  # se guardó EXACTAMENTE lo respondido


def test_api_guarda_tambien_los_reportes_con_error():
    # Arrange
    fake = AlmacenamientoEnMemoria()
    cliente = TestClient(crear_app(fake))

    # Act
    respuesta = cliente.post("/compilar", json={"codigo": "x = 1;"})

    # Assert
    assert respuesta.status_code == 422
    assert fake.reportes[0]["fase_alcanzada"] == "semantico"


def test_si_s3_falla_la_api_responde_igual(caplog):
    # Arrange
    cliente = TestClient(crear_app(AlmacenamientoQueFalla()))

    # Act
    respuesta = cliente.post("/compilar", json={"codigo": "print(1);"})

    # Assert: degradación elegante → 200 con el reporte, y queda registro del fallo.
    assert respuesta.status_code == 200
    assert respuesta.json()["salida"] == ["1"]
    assert respuesta.headers["X-Reporte-Guardado"] == "error"
    assert "S3 caído" in caplog.text


def test_sin_almacenamiento_lo_indica_en_la_cabecera():
    # Arrange
    cliente = TestClient(crear_app(AlmacenamientoNulo()))

    # Act
    respuesta = cliente.post("/compilar", json={"codigo": "print(1);"})

    # Assert
    assert respuesta.headers["X-Reporte-Guardado"] == "no-configurado"
    assert "X-Reporte-Clave" not in respuesta.headers


def test_crear_app_sin_argumentos_usa_el_entorno(monkeypatch):
    # Arrange
    monkeypatch.delenv("MINICOMPILADOR_BUCKET", raising=False)

    # Act
    respuesta = TestClient(crear_app()).post("/compilar", json={"codigo": "print(1);"})

    # Assert
    assert respuesta.headers["X-Reporte-Guardado"] == "no-configurado"
