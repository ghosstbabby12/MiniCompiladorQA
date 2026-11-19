"""Pruebas del análisis semántico: tabla de símbolos, tipos, errores y advertencias."""

import pytest

from minicompilador.ast_nodos import BinOp, Numero
from minicompilador.errores import ErrorSemantico
from minicompilador.parser import parsear
from minicompilador.semantico import AnalizadorSemantico, TablaSimbolos, a_snake_case, analizar


def analizar_codigo(codigo: str):
    """Helper: léxico + sintáctico + semántico."""
    return analizar(parsear(codigo))


def codigos_de_advertencia(codigo: str) -> list[str]:
    return [advertencia.codigo for advertencia in analizar_codigo(codigo).advertencias]


# ---------------------------------------------------------------------------
# Tabla de símbolos
# ---------------------------------------------------------------------------


def test_tabla_de_simbolos_del_programa_de_la_especificacion():
    # Arrange
    with open("ejemplos/validos/programa_especificacion.mini", encoding="utf-8") as archivo:
        codigo = archivo.read()

    # Act
    tabla = analizar_codigo(codigo).tabla.a_dict()

    # Assert
    assert list(tabla) == ["a", "b", "c"]  # en orden de declaración
    assert {nombre: datos["tipo"] for nombre, datos in tabla.items()} == {
        "a": "int",
        "b": "float",
        "c": "int",
    }
    assert [datos["direccion"] for datos in tabla.values()] == [1000, 1004, 1008]
    assert all(datos["inicializada"] for datos in tabla.values())


@pytest.mark.parametrize(
    ("cantidad", "ultima_direccion"),
    [
        (1, 1000),  # la primera variable vive en la base (no en 1004: off-by-one)
        (2, 1004),
        (10, 1036),  # 1000 + 4 * (10 - 1)
    ],
)
def test_direcciones_avanzan_de_a_una_palabra(cantidad, ultima_direccion):
    # Arrange
    tabla = TablaSimbolos()

    # Act
    for indice in range(cantidad):
        simbolo = tabla.declarar(f"v{indice}", "int", 1, 1, inicializada=True)

    # Assert
    assert simbolo.direccion == ultima_direccion
    assert len(tabla) == cantidad


@pytest.mark.parametrize(
    ("codigo", "inicializada"),
    [
        ("int total;", False),
        ("int total = 1;", True),
        ("int total;\ntotal = 1;", True),
    ],
)
def test_marca_si_la_variable_esta_inicializada(codigo, inicializada):
    # Arrange (en parámetros)
    # Act
    simbolo = analizar_codigo(codigo).tabla.buscar("total")

    # Assert
    assert simbolo.inicializada is inicializada


# ---------------------------------------------------------------------------
# Inferencia de tipos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expresion", "tipo"),
    [
        (BinOp(Numero(1), "+", Numero(2)), "int"),
        (BinOp(Numero(1), "+", Numero(2.0)), "float"),  # promoción numérica
        (BinOp(Numero(1.5), "%", Numero(2)), "float"),
        (BinOp(Numero(1), "<", Numero(2.5)), "bool"),
        (BinOp(Numero(True), "==", Numero(False)), "bool"),
        (BinOp(BinOp(Numero(1), "*", Numero(2)), "!=", Numero(3)), "bool"),
    ],
)
def test_inferencia_de_tipos_de_expresiones(expresion, tipo):
    # Arrange
    analizador = AnalizadorSemantico()

    # Act
    resultado = analizador.visitar(expresion)

    # Assert
    assert resultado == tipo


# ---------------------------------------------------------------------------
# Errores semánticos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "patron", "linea", "columna"),
    [
        # Variable no declarada: en una expresión y como destino de asignación.
        ("int a = b;", "'b' no ha sido declarada", 1, 9),
        ("x = 1;", "'x' no ha sido declarada", 1, 1),
        ("int a = a + 1;", "'a' no ha sido declarada", 1, 9),  # se usa antes de existir
        # Redeclaración: el error apunta a la SEGUNDA declaración.
        ("int a;\nfloat a;", "ya fue declarada en la línea 1", 2, 1),
        # Palabra reservada como nombre.
        ("int if = 5;", "'if' es una palabra reservada", 1, 1),
        ("bool true;", "'true' es una palabra reservada", 1, 1),
        ("float int = 1.0;", "'int' es una palabra reservada", 1, 1),
        # Tipos incompatibles.
        ("int a = true + 1;", r"'\+' no acepta valores bool", 1, 14),
        ("bool f = true < false;", "'<' no tiene sentido con valores bool", 1, 15),
        ("bool f = true == 1;", "No se puede comparar bool con int", 1, 15),
        ("int a = true;", "valor bool a la variable 'a' de tipo int", 1, 1),
        ("bool f = 1;", "valor int a la variable 'f' de tipo bool", 1, 1),
        ("bool f;\nf = 2.5;", "valor float a la variable 'f' de tipo bool", 2, 1),
    ],
)
def test_errores_semanticos(codigo, patron, linea, columna):
    # Arrange (en parámetros): un representante por cada clase de error.
    # Act
    with pytest.raises(ErrorSemantico, match=patron) as info:
        analizar_codigo(codigo)

    # Assert
    assert (info.value.linea, info.value.columna) == (linea, columna)
    assert info.value.fase == "semantico"
    assert info.value.sugerencia


def test_variable_no_declarada_dentro_de_un_bloque():
    # Arrange
    codigo = "int contador = 1;\nwhile (contador > 0) {\n    total = 0;\n}"

    # Act / Assert
    with pytest.raises(ErrorSemantico, match="'total' no ha sido declarada") as info:
        analizar_codigo(codigo)
    assert info.value.linea == 3


# ---------------------------------------------------------------------------
# Advertencias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "codigo_advertencia"),
    [
        ("int total;\ntotal = 2.5;\nprint(total);", "FLOAT_A_INT"),
        ("int total = 1.5;\nprint(total);", "FLOAT_A_INT"),
        ("int total;\nprint(total);", "NO_INICIALIZADA"),
        ("int total = 1;", "NO_USADA"),
        ("int total = 1;\nif (total) { print(total); }", "CONDICION_NO_BOOLEANA"),
        ("int list = 1;\nprint(list);", "NOMBRE_BUILTIN"),
        ("int len = 1;\nprint(len);", "NOMBRE_BUILTIN"),
        ("int t = 1;\nprint(t);", "NOMBRE_CORTO"),
        ("int miTotal = 1;\nprint(miTotal);", "NO_SNAKE_CASE"),
    ],
)
def test_cada_advertencia_se_emite_en_su_caso(codigo, codigo_advertencia):
    # Arrange (en parámetros)
    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert codigos == [codigo_advertencia]


def test_codigo_limpio_no_produce_advertencias():
    # Arrange: partición "buenas prácticas" (nombres descriptivos, todo usado).
    codigo = (
        "int contador = 3;\n"
        "float promedio = 0.0;\n"
        "while (contador > 0) {\n"
        "    promedio = promedio + 1.5;\n"
        "    contador = contador - 1;\n"
        "}\n"
        "print(promedio);\n"
    )

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert codigos == []


@pytest.mark.parametrize(
    ("nombre", "advierte"),
    [
        ("t", True),  # 1 carácter: ON point de la regla "nombre corto"
        ("tt", False),  # 2 caracteres: OFF point
    ],
)
def test_valor_limite_de_nombre_corto(nombre, advierte):
    # Arrange
    codigo = f"int {nombre} = 1;\nprint({nombre});"

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert ("NOMBRE_CORTO" in codigos) is advierte


def test_nombre_de_una_letra_es_valido_si_es_contador_de_while():
    # Arrange: 'i' aparece en la condición del while → es un contador.
    codigo = "int i = 3;\nwhile (i > 0) { i = i - 1; }"

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert "NOMBRE_CORTO" not in codigos


def test_contador_dentro_de_un_while_anidado_tambien_se_detecta():
    # Arrange: la pre-pasada recorre todo el árbol, no solo el primer nivel.
    codigo = "int j = 1;\nif (true) { while (j < 3) { j = j + 1; } }"

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert "NOMBRE_CORTO" not in codigos


def test_no_inicializada_se_advierte_una_sola_vez():
    # Arrange
    codigo = "int total;\nprint(total);\nprint(total + 1);"

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert codigos.count("NO_INICIALIZADA") == 1


def test_un_nombre_puede_acumular_varias_advertencias():
    # Arrange: 'L' es de una letra y además no es snake_case.
    codigo = "int L = 1;\nprint(L);"

    # Act
    codigos = codigos_de_advertencia(codigo)

    # Assert
    assert codigos == ["NOMBRE_CORTO", "NO_SNAKE_CASE"]


def test_programa_de_la_especificacion_tiene_las_advertencias_esperadas():
    # Arrange
    with open("ejemplos/validos/programa_especificacion.mini", encoding="utf-8") as archivo:
        codigo = archivo.read()

    # Act
    advertencias = analizar_codigo(codigo).advertencias

    # Assert: 'a' es contador del while; 'b' y 'c' no. 'c' recibe un float.
    assert [(a.codigo, a.linea) for a in advertencias] == [
        ("NOMBRE_CORTO", 3),
        ("NOMBRE_CORTO", 4),
        ("FLOAT_A_INT", 5),
    ]


def test_advertencia_a_dict():
    # Arrange
    advertencia = analizar_codigo("int t = 1;\nprint(t);").advertencias[0]

    # Act
    datos = advertencia.a_dict()

    # Assert
    assert datos["fase"] == "semantico"
    assert datos["codigo"] == "NOMBRE_CORTO"
    assert (datos["linea"], datos["columna"]) == (1, 1)
    assert datos["sugerencia"]


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [("miVariable", "mi_variable"), ("TOTAL", "total"), ("valorX2", "valor_x2")],
)
def test_sugerencia_snake_case(nombre, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = a_snake_case(nombre)

    # Assert
    assert resultado == esperado


def test_tabla_responde_si_contiene_un_nombre():
    # Arrange
    tabla = analizar_codigo("int total = 1;\nprint(total);").tabla

    # Act / Assert: partición "declarada" vs "no declarada".
    assert "total" in tabla
    assert "otra" not in tabla
