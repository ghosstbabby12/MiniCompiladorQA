"""Pruebas de la jerarquía de errores (``minicompilador.errores``)."""

import pytest

from minicompilador.errores import (
    FASES,
    ErrorCompilador,
    ErrorEjecucion,
    ErrorLexico,
    ErrorSemantico,
    ErrorSintactico,
)


@pytest.mark.parametrize(
    ("clase", "fase_esperada"),
    [
        (ErrorLexico, "lexico"),
        (ErrorSintactico, "sintactico"),
        (ErrorSemantico, "semantico"),
        (ErrorEjecucion, "simulacion"),
    ],
)
def test_cada_error_hereda_de_la_base_y_conoce_su_fase(clase, fase_esperada):
    # Arrange
    error = clase("mensaje", 1, 1)

    # Act
    es_error_compilador = isinstance(error, ErrorCompilador)

    # Assert
    assert es_error_compilador
    assert error.fase == fase_esperada
    assert error.fase in FASES
    assert error.tipo == clase.__name__


def test_a_dict_expone_todos_los_campos_del_reporte():
    # Arrange
    error = ErrorLexico("Carácter no reconocido '@'.", 3, 7, sugerencia="Elimínalo.")

    # Act
    datos = error.a_dict()

    # Assert
    assert datos == {
        "fase": "lexico",
        "tipo": "ErrorLexico",
        "mensaje": "Carácter no reconocido '@'.",
        "linea": 3,
        "columna": 7,
        "sugerencia": "Elimínalo.",
    }


@pytest.mark.parametrize(
    ("linea", "columna", "texto_esperado"),
    [
        # Partición 1: con línea y columna.
        (2, 5, "[Semántico] línea 2, columna 5: x"),
        # Partición 2: solo línea.
        (2, None, "[Semántico] línea 2: x"),
        # Partición 3: sin posición (errores globales, ej. límite de ciclos).
        (None, None, "[Semántico]: x"),
    ],
)
def test_str_formatea_la_posicion_segun_lo_disponible(linea, columna, texto_esperado):
    # Arrange
    error = ErrorSemantico("x", linea, columna)

    # Act
    texto = str(error)

    # Assert
    assert texto == texto_esperado


def test_str_incluye_la_sugerencia_cuando_existe():
    # Arrange
    error = ErrorEjecucion("División por cero.", 4, 1, sugerencia="Verifica el divisor.")

    # Act
    texto = str(error)

    # Assert
    assert texto.endswith("Sugerencia: Verifica el divisor.")


def test_la_base_atrapa_errores_de_cualquier_fase():
    # Arrange
    def falla():
        raise ErrorSintactico("Falta ';'.", 1, 10)

    # Act / Assert: capturar por la clase base demuestra polimorfismo (Liskov).
    with pytest.raises(ErrorCompilador, match="Falta ';'"):
        falla()
