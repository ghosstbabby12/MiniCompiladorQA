"""Pruebas de componente de la API (en proceso, con ``TestClient``).

Diferencia con ``tests/api`` (pruebas de CONTRATO):
    * Aquí la app corre dentro de pytest: rápido, sin red, y mide cobertura.
    * En ``tests/api`` un cliente externo habla HTTP real con el contenedor,
      como lo haría cualquier consumidor de la API.

Partición de equivalencia de las solicitudes a /compilar:
    =========================  ======  =========================================
    Clase                      HTTP    Ejemplo
    =========================  ======  =========================================
    válida, programa correcto  200     ``{"codigo": "print(1);"}``
    válida, programa con error 422     ``{"codigo": "%a = 1;"}``
    inválida (forma/rango)     400     ``{}``, ``{"codigo": 5}``, hasta_fase=7
    =========================  ======  =========================================
"""

import pytest
from fastapi.testclient import TestClient

from minicompilador import __version__
from minicompilador.api import LIMITE_CICLOS_MAXIMO, LONGITUD_MAXIMA_CODIGO, app
from minicompilador.reporte import cargar_esquema, errores_de_esquema

ESPEC = "ejemplos/validos/programa_especificacion.mini"


@pytest.fixture(scope="module")
def cliente():
    return TestClient(app)


def leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as archivo:
        return archivo.read()


def test_salud(cliente):
    # Arrange / Act
    respuesta = cliente.get("/salud")

    # Assert
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok", "version": __version__}


def test_esquema_publicado_es_el_del_paquete(cliente):
    # Arrange / Act
    respuesta = cliente.get("/esquema")

    # Assert
    assert respuesta.status_code == 200
    assert respuesta.json() == cargar_esquema()


def test_compilar_programa_valido_devuelve_200_y_reporte(cliente):
    # Arrange
    cuerpo = {"codigo": leer(ESPEC)}

    # Act
    respuesta = cliente.post("/compilar", json=cuerpo)

    # Assert
    assert respuesta.status_code == 200
    reporte = respuesta.json()
    assert reporte["salida"] == ["3"]
    assert errores_de_esquema(reporte) == []


@pytest.mark.parametrize(
    ("codigo", "fase"),
    [
        ("%a = 1;", "lexico"),
        ("int a = ;", "sintactico"),
        ("x = 1;", "semantico"),
        ("int x = 1 / 0;", "simulacion"),
    ],
)
def test_programa_con_error_devuelve_422_con_reporte_valido(cliente, codigo, fase):
    # Arrange: una muestra de cada clase de error del programa.
    # Act
    respuesta = cliente.post("/compilar", json={"codigo": codigo})

    # Assert
    assert respuesta.status_code == 422
    reporte = respuesta.json()
    assert reporte["fase_alcanzada"] == fase
    assert reporte["errores"][0]["fase"] == fase
    assert errores_de_esquema(reporte) == []


def test_hasta_fase_y_limite_ciclos_se_respetan(cliente):
    # Arrange
    cuerpo = {"codigo": leer(ESPEC), "hasta_fase": 3, "limite_ciclos": 10}

    # Act
    reporte = cliente.post("/compilar", json=cuerpo).json()

    # Assert: se detuvo en la fase 3, así que el límite de ciclos ni se usó.
    assert reporte["fases_completadas"] == ["lexico", "sintactico", "semantico"]
    assert reporte["metricas"] is None


@pytest.mark.parametrize(
    ("cuerpo", "campo"),
    [
        ({}, "codigo"),  # falta el campo obligatorio
        ({"codigo": 5}, "codigo"),  # tipo incorrecto
        ({"codigo": "x", "hasta_fase": "6"}, "hasta_fase"),  # strict: "6" no es 6
        ({"codigo": "x", "hasta_fase": True}, "hasta_fase"),  # strict: bool no es int
        ({"codigo": "x", "hasta_fase": 0}, "hasta_fase"),  # off point inferior
        ({"codigo": "x", "hasta_fase": 7}, "hasta_fase"),  # off point superior
        ({"codigo": "x", "limite_ciclos": 0}, "limite_ciclos"),
        ({"codigo": "x", "limite_ciclos": LIMITE_CICLOS_MAXIMO + 1}, "limite_ciclos"),
        ({"codigo": "x" * (LONGITUD_MAXIMA_CODIGO + 1)}, "codigo"),  # off point
        ({"codigo": "x", "hasta_fse": 3}, "hasta_fse"),  # campo desconocido
    ],
)
def test_solicitud_invalida_devuelve_400_explicando_el_campo(cliente, cuerpo, campo):
    # Arrange (en parámetros)
    # Act
    respuesta = cliente.post("/compilar", json=cuerpo)

    # Assert
    assert respuesta.status_code == 400
    datos = respuesta.json()
    assert datos["error"] == "solicitud_invalida"
    assert campo in [d["campo"] for d in datos["detalle"]]


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"codigo": "print(1);", "hasta_fase": 1},  # on point inferior
        {"codigo": "print(1);", "hasta_fase": 6},  # on point superior
        {"codigo": "print(1);", "limite_ciclos": 2},  # print(1) cuesta 2 ciclos
        {"codigo": "", "limite_ciclos": LIMITE_CICLOS_MAXIMO},
        {"codigo": " " * LONGITUD_MAXIMA_CODIGO},  # on point de la longitud
    ],
)
def test_valores_en_el_borde_de_los_rangos_se_aceptan(cliente, cuerpo):
    # Arrange (en parámetros)
    # Act
    respuesta = cliente.post("/compilar", json=cuerpo)

    # Assert
    assert respuesta.status_code == 200


def test_json_mal_formado_devuelve_400(cliente):
    # Arrange
    cuerpo_roto = '{"codigo": "print(1);"'  # falta la llave de cierre

    # Act
    respuesta = cliente.post(
        "/compilar", content=cuerpo_roto, headers={"Content-Type": "application/json"}
    )

    # Assert
    assert respuesta.status_code == 400
    assert respuesta.json()["detalle"][0]["tipo"] == "json_invalid"


def test_metodo_no_permitido(cliente):
    # Arrange / Act
    respuesta = cliente.get("/compilar")

    # Assert
    assert respuesta.status_code == 405


@pytest.mark.parametrize(
    ("codigo", "estado", "fragmento"),
    [
        ("print(1);", 200, "Resultado: ÉXITO."),
        ("int a = 5;\nint b = a @ 2;", 422, "Análisis del error"),
    ],
)
def test_explicar_devuelve_texto_plano(cliente, codigo, estado, fragmento):
    # Arrange
    cuerpo = {"codigo": codigo}

    # Act
    respuesta = cliente.post("/explicar", json=cuerpo)

    # Assert
    assert respuesta.status_code == estado
    assert respuesta.headers["content-type"].startswith("text/plain")
    assert fragmento in respuesta.text


def test_desbordamiento_no_rompe_el_json(cliente):
    # Arrange: antes de limitar los rangos, 'inf' hacía fallar json.dumps (HTTP 500).
    codigo = "float x = 10.0;\nwhile (x > 0.0) { x = x * 10.0; }"

    # Act
    respuesta = cliente.post("/compilar", json={"codigo": codigo})

    # Assert
    assert respuesta.status_code == 422
    assert "Desbordamiento" in respuesta.json()["errores"][0]["mensaje"]
