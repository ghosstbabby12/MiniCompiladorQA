"""Pruebas del generador de código intermedio (TAC)."""

import pytest

from minicompilador.errores import ErrorLexico
from minicompilador.intermedio import GeneradorIntermedio, generar_intermedio
from minicompilador.lexer import tokenizar
from minicompilador.parser import parsear


def tac(codigo: str, plegar: bool = True) -> list[str]:
    """Helper: código Mini → lista de instrucciones TAC como texto."""
    return generar_intermedio(parsear(codigo), plegar).como_texto()


# ---------------------------------------------------------------------------
# Expresiones, temporales y recorrido
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("x = a;", ["x = a"]),  # sin operación: no hace falta temporal
        ("x = a + b;", ["%t1 = a + b", "x = %t1"]),
        # Precedencia: primero la multiplicación (está más abajo en el árbol).
        ("x = a + b * c;", ["%t1 = b * c", "%t2 = a + %t1", "x = %t2"]),
        ("x = (a + b) * c;", ["%t1 = a + b", "%t2 = %t1 * c", "x = %t2"]),
        # Asociatividad izquierda: (a - b) - c
        ("x = a - b - c;", ["%t1 = a - b", "%t2 = %t1 - c", "x = %t2"]),
        ("print(a % b);", ["%t1 = a % b", "print %t1"]),
        ("bool f = a < b;", ["%t1 = a < b", "f = %t1"]),
        ("int c;", []),  # declarar sin valor no genera código
    ],
)
def test_traduccion_de_expresiones_a_tres_direcciones(codigo, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == esperado


def test_temporales_y_sus_definiciones():
    # Arrange
    codigo = "x = a + b * c;"

    # Act
    resultado = generar_intermedio(parsear(codigo))

    # Assert
    assert resultado.temporales == ["%t1", "%t2"]
    assert resultado.total_temporales == 2
    assert resultado.definiciones_temporales == {
        "%t1": "%t1 = b * c",
        "%t2": "%t2 = a + %t1",
    }


def test_nueva_temporal_empieza_en_uno_y_es_secuencial():
    # Arrange: off-by-one, la primera temporal es %t1 (no %t0).
    generador = GeneradorIntermedio()

    # Act
    nombres = [generador.nueva_temporal() for _ in range(3)]

    # Assert
    assert nombres == ["%t1", "%t2", "%t3"]


@pytest.mark.parametrize("temporal", ["%t1", "%t2", "%t99"])
def test_el_usuario_no_puede_escribir_una_temporal(temporal):
    # Arrange: prueba ENTRE FASES. Si el lexer rechaza el nombre, es imposible
    # que una temporal choque con una variable del usuario.
    codigo = f"{temporal} = 5;"

    # Act / Assert
    with pytest.raises(ErrorLexico, match="no es un identificador válido"):
        tokenizar(codigo)


def test_recorrido_es_dfs_en_postorden():
    # Arrange
    codigo = "x = a + b * 2;"

    # Act
    recorrido = generar_intermedio(parsear(codigo), plegar_constantes=False).recorrido

    # Assert: cada nodo aparece DESPUÉS de todos sus hijos.
    assert recorrido == [
        "Variable a",
        "Variable b",
        "Numero 2 (int)",
        "BinOp '*'",
        "BinOp '+'",
        "Asignacion x =",
        "Programa",
    ]


def test_las_instrucciones_recuerdan_su_linea_de_origen():
    # Arrange
    codigo = "int a = 1;\nprint(a + 1);"

    # Act
    instrucciones = generar_intermedio(parsear(codigo)).instrucciones

    # Assert
    assert [i.linea for i in instrucciones] == [1, 2, 2]


# ---------------------------------------------------------------------------
# Plegado de constantes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expresion", "valor"),
    [
        ("2 * 3", "6"),
        ("2 + 3 * 4", "14"),  # plegado en cascada: sin ninguna temporal
        ("7 / 2", "3"),  # división entera estilo C
        ("-7 / 2", "-3"),
        ("7.0 / 2", "3.5"),
        ("7 % 3", "1"),
        ("1 < 2", "true"),
        ("true == false", "false"),
    ],
)
def test_plegado_de_constantes(expresion, valor):
    # Arrange
    codigo = f"x = {expresion};"

    # Act
    resultado = generar_intermedio(parsear(codigo))

    # Assert
    assert resultado.como_texto() == [f"x = {valor}"]
    assert resultado.total_temporales == 0
    assert resultado.optimizaciones


def test_plegado_parcial_solo_de_la_parte_constante():
    # Arrange
    codigo = "x = 2 * 3 + a;"

    # Act
    resultado = generar_intermedio(parsear(codigo))

    # Assert
    assert resultado.como_texto() == ["%t1 = 6 + a", "x = %t1"]
    assert resultado.optimizaciones == ["Línea 1: 2 * 3 → 6"]


@pytest.mark.parametrize("expresion", ["5 / 0", "5 % 0", "5.0 / 0.0"])
def test_division_por_cero_constante_no_se_pliega(expresion):
    # Arrange: el optimizador no debe ocultar el error de ejecución.
    codigo = f"x = {expresion};"

    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == [f"%t1 = {expresion}", "x = %t1"]


def test_desbordamiento_constante_no_se_pliega():
    # Arrange: igual que la división por cero, el error se reporta al ejecutar.
    codigo = "x = 2147483647 + 1;"

    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == ["%t1 = 2147483647 + 1", "x = %t1"]


def test_sin_plegado_se_genera_la_operacion():
    # Arrange
    codigo = "x = 2 * 3;"

    # Act
    resultado = tac(codigo, plegar=False)

    # Assert
    assert resultado == ["%t1 = 2 * 3", "x = %t1"]


# ---------------------------------------------------------------------------
# Control de flujo
# ---------------------------------------------------------------------------


def test_if_sin_else():
    # Arrange
    codigo = "if (a > 0) { print(a); }"

    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == ["%t1 = a > 0", "ifFalse %t1 goto L1", "print a", "L1:"]


def test_if_con_else():
    # Arrange
    codigo = "if (a > 0) { print(a); } else { print(0); }"

    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == [
        "%t1 = a > 0",
        "ifFalse %t1 goto L1",
        "print a",
        "goto L2",
        "L1:",
        "print 0",
        "L2:",
    ]


def test_while_recalcula_la_condicion_en_cada_vuelta():
    # Arrange
    codigo = "while (a > 0) { a = a - 1; }"

    # Act
    resultado = tac(codigo)

    # Assert: la condición queda DESPUÉS de la etiqueta de inicio.
    assert resultado == [
        "L1:",
        "%t1 = a > 0",
        "ifFalse %t1 goto L2",
        "%t2 = a - 1",
        "a = %t2",
        "goto L1",
        "L2:",
    ]


def test_condicion_booleana_literal():
    # Arrange
    codigo = "while (true) { }"

    # Act
    resultado = tac(codigo)

    # Assert
    assert resultado == ["L1:", "ifFalse true goto L2", "goto L1", "L2:"]


def test_programa_de_la_especificacion_completo():
    # Arrange: prueba "golden" del programa de referencia.
    with open("ejemplos/validos/programa_especificacion.mini", encoding="utf-8") as archivo:
        codigo = archivo.read()

    # Act
    resultado = generar_intermedio(parsear(codigo))

    # Assert
    assert resultado.como_texto() == [
        "a = 5",
        "b = 2.5",
        "%t1 = a - 2",
        "%t2 = b * %t1",
        "%t3 = %t2 % 3",
        "%t4 = a + %t3",
        "c = %t4",
        "%t5 = c > 10",
        "ifFalse %t5 goto L1",
        "print c",
        "goto L2",
        "L1:",
        "%t6 = c / 2",
        "c = %t6",
        "print c",
        "L2:",
        "L3:",
        "%t7 = a > 0",
        "ifFalse %t7 goto L4",
        "%t8 = a - 1",
        "a = %t8",
        "goto L3",
        "L4:",
    ]
    assert resultado.total_temporales == 8
