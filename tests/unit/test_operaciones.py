"""Pruebas de la semántica de operadores (compartida por optimizador y CPU)."""

import pytest

from minicompilador.operaciones import division_entera_c, evaluar_binaria


@pytest.mark.parametrize(
    ("op", "izquierda", "derecha", "esperado"),
    [
        ("+", 2, 3, 5),
        ("-", 2, 3, -1),
        ("*", 2, 3.0, 6.0),
        # División entera trunca hacia cero (como C), en las 4 combinaciones de signo.
        ("/", 7, 2, 3),
        ("/", -7, 2, -3),  # Python: -7 // 2 == -4  ← aquí está la diferencia
        ("/", 7, -2, -3),
        ("/", -7, -2, 3),
        ("/", 7.0, 2, 3.5),  # si hay float, división real
        # Módulo: el signo es el del dividendo (como C).
        ("%", 7, 3, 1),
        ("%", -7, 2, -1),  # Python: -7 % 2 == 1
        ("%", 7, -2, 1),
        ("%", 5.5, 2, 1.5),
        ("<", 1, 2, True),
        (">", 1, 2, False),
        ("<=", 2, 2, True),  # valor límite: igualdad en <=
        (">=", 1, 2, False),
        ("==", True, True, True),
        ("!=", 1, 1.0, False),
    ],
)
def test_evaluar_binaria_sigue_la_semantica_de_c(op, izquierda, derecha, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = evaluar_binaria(op, izquierda, derecha)

    # Assert
    assert resultado == esperado
    assert type(resultado) is type(esperado)


@pytest.mark.parametrize(
    ("op", "divisor"),
    [("/", 0), ("%", 0), ("/", 0.0), ("%", 0.0)],
)
def test_division_por_cero_lanza_zero_division_error(op, divisor):
    # Arrange: valor límite "cero" del divisor (entero y real).
    # Act / Assert
    with pytest.raises(ZeroDivisionError, match=f"5 {op} 0"):
        evaluar_binaria(op, 5, divisor)


@pytest.mark.parametrize("divisor", [1, -1])
def test_divisores_vecinos_del_cero_si_son_validos(divisor):
    # Arrange: off points alrededor del cero (1 y -1).
    # Act
    resultado = evaluar_binaria("/", 5, divisor)

    # Assert
    assert resultado == 5 * divisor


def test_division_entera_c_no_pierde_precision_con_enteros_grandes():
    # Arrange: 10**20 + 1 no cabe exacto en un float; int(a / b) fallaría.
    dividendo = 10**20 + 1

    # Act
    resultado = division_entera_c(dividendo, 1)

    # Assert
    assert resultado == dividendo


def test_operador_desconocido():
    # Arrange
    op = "**"

    # Act / Assert
    with pytest.raises(ValueError, match="Operador desconocido"):
        evaluar_binaria(op, 2, 3)


# ---------------------------------------------------------------------------
# Rango numérico: int de 32 bits y float finito
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "izquierda", "derecha", "esperado"),
    [
        ("+", 2147483646, 1, 2147483647),  # on point: el máximo exacto
        ("-", -2147483647, 1, -2147483648),  # on point: el mínimo exacto
        ("*", 1e300, 1e8, 1e308),  # real grande pero finito
    ],
)
def test_resultados_en_el_borde_del_rango_son_validos(op, izquierda, derecha, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = evaluar_binaria(op, izquierda, derecha)

    # Assert
    assert resultado == esperado


@pytest.mark.parametrize(
    ("op", "izquierda", "derecha", "mensaje"),
    [
        ("+", 2147483647, 1, "2147483648 no cabe"),  # off point superior
        ("-", -2147483648, 1, "-2147483649 no cabe"),  # off point inferior
        ("*", 65536, 65536, "no cabe en un int de 32 bits"),
        ("*", 1e308, 10.0, "infinito"),
    ],
)
def test_resultados_fuera_de_rango_lanzan_overflow_error(op, izquierda, derecha, mensaje):
    # Arrange (en parámetros)
    # Act / Assert
    with pytest.raises(OverflowError, match=mensaje):
        evaluar_binaria(op, izquierda, derecha)


def test_los_booleanos_no_se_validan_como_enteros():
    # Arrange / Act
    resultado = evaluar_binaria("<", 1, 2)

    # Assert
    assert resultado is True
