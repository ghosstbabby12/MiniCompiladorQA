"""Pruebas del orquestador y del contrato JSON (JSON Schema)."""

import json
from pathlib import Path

import pytest

from minicompilador.errores import FASES
from minicompilador.reporte import cargar_esquema, compilar, compilar_a_reporte, errores_de_esquema

EJEMPLOS = Path("ejemplos")
ESPEC = (EJEMPLOS / "validos" / "programa_especificacion.mini").read_text(encoding="utf-8")

#: Prefijo del nombre del ejemplo → fase donde DEBE detenerse.
FASE_POR_PREFIJO = {
    "lexico": "lexico",
    "sintactico": "sintactico",
    "semantico": "semantico",
    "ejecucion": "simulacion",
}


def test_reporte_exitoso_tiene_todas_las_secciones():
    # Arrange
    codigo = ESPEC

    # Act
    reporte = compilar_a_reporte(codigo)

    # Assert
    assert reporte["exito"] is True
    assert reporte["fase_alcanzada"] == "simulacion"
    assert reporte["fases_completadas"] == list(FASES)
    assert reporte["salida"] == ["3"]
    assert reporte["total_temporales"] == len(reporte["temporales"]) == 8
    assert reporte["registros_max_simultaneos"] == 2
    assert reporte["spills"] == 0
    assert reporte["errores"] == []
    assert reporte["instrucciones_cpu"][-1] == "HALT"
    assert errores_de_esquema(reporte) == []


def test_reporte_es_serializable_a_json():
    # Arrange
    reporte = compilar_a_reporte(ESPEC)

    # Act
    texto = json.dumps(reporte)

    # Assert
    assert json.loads(texto) == reporte


@pytest.mark.parametrize(
    "archivo",
    sorted((EJEMPLOS / "errores").glob("*.mini")),
    ids=lambda ruta: ruta.stem,
)
def test_cada_ejemplo_con_error_se_detiene_en_su_fase(archivo):
    # Arrange: el prefijo del nombre del archivo indica la fase esperada.
    fase_esperada = FASE_POR_PREFIJO[archivo.stem.split("_")[0]]
    codigo = archivo.read_text(encoding="utf-8")

    # Act
    reporte = compilar_a_reporte(codigo, limite_ciclos=5_000)

    # Assert
    assert reporte["exito"] is False
    assert reporte["fase_alcanzada"] == fase_esperada
    assert reporte["errores"][0]["fase"] == fase_esperada
    assert reporte["errores"][0]["linea"] is not None
    assert errores_de_esquema(reporte) == []


@pytest.mark.parametrize(
    "archivo",
    sorted((EJEMPLOS / "validos").glob("*.mini")),
    ids=lambda ruta: ruta.stem,
)
def test_cada_ejemplo_valido_llega_a_la_simulacion(archivo):
    # Arrange
    codigo = archivo.read_text(encoding="utf-8")

    # Act
    reporte = compilar_a_reporte(codigo)

    # Assert
    assert reporte["exito"] is True
    assert errores_de_esquema(reporte) == []


def test_hay_al_menos_un_ejemplo_por_tipo_de_error():
    # Arrange
    prefijos = {ruta.stem.split("_")[0] for ruta in (EJEMPLOS / "errores").glob("*.mini")}

    # Act / Assert
    assert prefijos == set(FASE_POR_PREFIJO)


@pytest.mark.parametrize(
    ("codigo", "fase", "secciones_nulas"),
    [
        ("%a = 1;", "lexico", ["tokens", "ast", "tabla_simbolos", "metricas"]),
        ("int a = ;", "sintactico", ["ast", "tabla_simbolos", "codigo_intermedio"]),
        ("x = 1;", "semantico", ["tabla_simbolos", "codigo_intermedio", "instrucciones_cpu"]),
    ],
)
def test_secciones_de_fases_no_alcanzadas_son_null(codigo, fase, secciones_nulas):
    # Arrange (en parámetros)
    # Act
    reporte = compilar_a_reporte(codigo)

    # Assert
    assert reporte["fase_alcanzada"] == fase
    for seccion in secciones_nulas:
        assert reporte[seccion] is None, seccion
    assert errores_de_esquema(reporte) == []


def test_tokens_presentes_si_el_error_es_sintactico():
    # Arrange: el léxico SÍ terminó, así que sus resultados deben verse.
    codigo = "int a = ;"

    # Act
    reporte = compilar_a_reporte(codigo)

    # Assert
    assert reporte["fases_completadas"] == ["lexico"]
    assert reporte["tokens"][0] == {"tipo": "TIPO", "valor": "int", "linea": 1, "columna": 1}


@pytest.mark.parametrize("hasta_fase", range(1, len(FASES) + 1))
def test_hasta_fase_detiene_la_compilacion(hasta_fase):
    # Arrange
    codigo = ESPEC

    # Act
    compilacion = compilar(codigo, hasta_fase=hasta_fase)

    # Assert
    assert compilacion.exito
    assert compilacion.fases_completadas == list(FASES[:hasta_fase])
    assert compilacion.fase_alcanzada == FASES[hasta_fase - 1]
    assert errores_de_esquema(compilacion.a_reporte()) == []


@pytest.mark.parametrize("hasta_fase", [0, 7])
def test_hasta_fase_fuera_de_rango(hasta_fase):
    # Arrange: off points del rango válido 1..6.
    # Act / Assert
    with pytest.raises(ValueError, match="entre 1 y 6"):
        compilar("print(1);", hasta_fase=hasta_fase)


def test_reporte_incluye_advertencias_de_varias_fases():
    # Arrange
    codigo = (EJEMPLOS / "validos" / "spill_registros.mini").read_text(encoding="utf-8")

    # Act
    reporte = compilar_a_reporte(codigo)

    # Assert
    fases = {a["fase"] for a in reporte["advertencias"]}
    assert fases == {"semantico", "registros"}
    assert reporte["spills"] == 1


# ---------------------------------------------------------------------------
# El esquema también rechaza reportes inválidos (prueba del propio contrato)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("modificar", "fragmento"),
    [
        (lambda r: r.pop("salida"), "'salida' is a required property"),
        (lambda r: r.update(fase_alcanzada="optimizacion"), "fase_alcanzada"),
        (lambda r: r.update(spills=-1), "spills"),
        (lambda r: r.update(registros_max_simultaneos=5), "registros_max_simultaneos"),
        (lambda r: r.update(temporales=["t1"]), "temporales/0"),
        (lambda r: r.update(extra=True), "Additional properties"),
        (lambda r: r.update(exito=False), "errores"),  # exito=false exige errores
    ],
)
def test_esquema_detecta_reportes_invalidos(modificar, fragmento):
    # Arrange
    reporte = compilar_a_reporte(ESPEC)
    modificar(reporte)

    # Act
    errores = errores_de_esquema(reporte)

    # Assert
    assert any(fragmento in error for error in errores), errores


def test_el_esquema_es_un_json_schema_valido():
    # Arrange / Act
    esquema = cargar_esquema()

    # Assert
    assert esquema["$schema"].endswith("2020-12/schema")
