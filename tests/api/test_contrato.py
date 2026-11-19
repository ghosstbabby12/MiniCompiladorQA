"""Pruebas de CONTRATO de la API: HTTP real + JSON Schema.

¿Qué es el contrato? Lo que un cliente puede dar por garantizado:
    1. Los códigos HTTP: 200 / 422 / 400 según la solicitud y el programa.
    2. La FORMA del cuerpo: todo reporte (200 o 422) cumple el JSON Schema.
    3. El esquema publicado no cambia sin que el consumidor se entere.

Si alguien renombra una clave del reporte, agrega una fase o cambia un código
HTTP, estas pruebas fallan ANTES de que el cambio llegue a producción.

Ejecución:
    docker compose up --build --abort-on-container-exit --exit-code-from test-runner
    # o, con la API corriendo en local:
    API_URL=http://localhost:8000 pytest tests/api -o addopts=""
"""

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

EJEMPLOS = Path(__file__).resolve().parents[2] / "ejemplos"
FASE_POR_PREFIJO = {
    "lexico": "lexico",
    "sintactico": "sintactico",
    "semantico": "semantico",
    "ejecucion": "simulacion",
}


def assert_cumple_esquema(reporte: dict, esquema: dict) -> None:
    errores = [e.message for e in Draft202012Validator(esquema).iter_errors(reporte)]
    assert errores == [], errores


def leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Endpoints de operación y del propio contrato
# ---------------------------------------------------------------------------


def test_salud_responde_ok(url_api, http):
    # Arrange
    url = f"{url_api}/salud"

    # Act
    respuesta = http.get(url, timeout=5)

    # Assert
    assert respuesta.status_code == 200
    assert respuesta.headers["Content-Type"] == "application/json"
    assert respuesta.json()["estado"] == "ok"


def test_esquema_publicado_es_json_schema_valido(esquema_publicado):
    # Arrange / Act / Assert: si el esquema es inválido, check_schema lanza.
    Draft202012Validator.check_schema(esquema_publicado)


def test_esquema_publicado_coincide_con_el_versionado(esquema_publicado, esquema_del_consumidor):
    # Arrange (fixtures): el del servidor vs. el del repositorio.
    # Act / Assert: cualquier cambio del contrato debe hacerse a propósito y en
    # ambos lados; si alguien lo cambia solo en el servidor, esta prueba avisa.
    assert esquema_publicado == esquema_del_consumidor


# ---------------------------------------------------------------------------
# POST /compilar - partición de equivalencia: 200 / 422 / 400
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "archivo",
    sorted((EJEMPLOS / "validos").glob("*.mini")),
    ids=lambda ruta: ruta.stem,
)
def test_programa_valido_200_y_cumple_esquema(url_api, http, esquema_publicado, archivo):
    # Arrange
    cuerpo = {"codigo": leer(archivo)}

    # Act
    respuesta = http.post(f"{url_api}/compilar", json=cuerpo, timeout=10)

    # Assert
    assert respuesta.status_code == 200
    reporte = respuesta.json()
    assert reporte["exito"] is True
    assert reporte["fase_alcanzada"] == "simulacion"
    assert_cumple_esquema(reporte, esquema_publicado)


def test_programa_de_la_especificacion_valores_exactos(url_api, http):
    # Arrange: oráculo calculado a mano en las etapas anteriores.
    cuerpo = {"codigo": leer(EJEMPLOS / "validos" / "programa_especificacion.mini")}

    # Act
    reporte = http.post(f"{url_api}/compilar", json=cuerpo, timeout=10).json()

    # Assert
    assert reporte["salida"] == ["3"]
    assert reporte["total_temporales"] == 8
    assert reporte["registros_max_simultaneos"] == 2
    assert reporte["memoria_final"] == {"a": 0, "b": 2.5, "c": 3}


@pytest.mark.parametrize(
    "archivo",
    sorted((EJEMPLOS / "errores").glob("*.mini")),
    ids=lambda ruta: ruta.stem,
)
def test_programa_con_error_422_y_cumple_esquema(url_api, http, esquema_publicado, archivo):
    # Arrange: el prefijo del archivo indica en qué fase debe fallar.
    fase = FASE_POR_PREFIJO[archivo.stem.split("_")[0]]
    cuerpo = {"codigo": leer(archivo), "limite_ciclos": 5_000}

    # Act
    respuesta = http.post(f"{url_api}/compilar", json=cuerpo, timeout=10)

    # Assert
    assert respuesta.status_code == 422
    reporte = respuesta.json()
    assert reporte["exito"] is False
    assert reporte["fase_alcanzada"] == fase
    error = reporte["errores"][0]
    assert error["linea"] is not None
    assert error["mensaje"]
    assert_cumple_esquema(reporte, esquema_publicado)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"codigo": None},
        {"codigo": "print(1);", "hasta_fase": 0},
        {"codigo": "print(1);", "hasta_fase": 7},
        {"codigo": "print(1);", "hasta_fase": "6"},
        {"codigo": "print(1);", "otro": 1},
    ],
    ids=["vacio", "codigo_null", "fase_0", "fase_7", "fase_texto", "campo_extra"],
)
def test_solicitud_invalida_400(url_api, http, cuerpo):
    # Arrange (en parámetros)
    # Act
    respuesta = http.post(f"{url_api}/compilar", json=cuerpo, timeout=5)

    # Assert
    assert respuesta.status_code == 400
    assert respuesta.json()["error"] == "solicitud_invalida"


def test_json_roto_400(url_api, http):
    # Arrange
    cabeceras = {"Content-Type": "application/json"}

    # Act
    respuesta = http.post(f"{url_api}/compilar", data="{no es json", headers=cabeceras, timeout=5)

    # Assert
    assert respuesta.status_code == 400


@pytest.mark.parametrize("fase", range(1, 7))
def test_hasta_fase_cumple_esquema_en_cada_fase(url_api, http, esquema_publicado, fase):
    # Arrange
    cuerpo = {"codigo": leer(EJEMPLOS / "validos" / "programa_especificacion.mini")}
    cuerpo["hasta_fase"] = fase

    # Act
    respuesta = http.post(f"{url_api}/compilar", json=cuerpo, timeout=10)

    # Assert: las secciones de fases no alcanzadas son null, y aun así es válido.
    assert respuesta.status_code == 200
    reporte = respuesta.json()
    assert len(reporte["fases_completadas"]) == fase
    assert_cumple_esquema(reporte, esquema_publicado)


def test_explicar_devuelve_texto(url_api, http):
    # Arrange
    cuerpo = {"codigo": "int a = 2;\nprint(a * 3);"}

    # Act
    respuesta = http.post(f"{url_api}/explicar", json=cuerpo, timeout=10)

    # Assert
    assert respuesta.status_code == 200
    assert respuesta.headers["Content-Type"].startswith("text/plain")
    assert "Salida del programa: 6" in respuesta.text
