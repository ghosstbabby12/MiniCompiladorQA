"""Pruebas unitarias del parser descendente recursivo.

Técnicas demostradas:
    * Comparación de árboles completos gracias a ``compare=False`` en posiciones.
    * Precedencia y asociatividad probadas con tablas (``parametrize``).
    * Valor límite de profundidad: 100 niveles (on point) vs 101 (off point).
    * Off-by-one en la columna reportada para un ';' faltante.
"""

import pytest

from minicompilador.ast_nodos import (
    Asignacion,
    BinOp,
    Declaracion,
    If,
    Numero,
    Print,
    Programa,
    Variable,
    While,
)
from minicompilador.errores import ErrorSintactico
from minicompilador.lexer import tokenizar
from minicompilador.parser import PROFUNDIDAD_MAXIMA, Parser, parsear

# Atajos para escribir árboles esperados de forma compacta.
V, N = Variable, Numero


def expresion_de(codigo_expresion: str):
    """Helper: parsea ``x = <expresion>;`` y devuelve solo la expresión."""
    return parsear(f"x = {codigo_expresion};").sentencias[0].valor


# ---------------------------------------------------------------------------
# Sentencias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("int a;", Declaracion("int", "a")),
        ("int a = 5;", Declaracion("int", "a", N(5))),
        ("float b = 2.5;", Declaracion("float", "b", N(2.5))),
        ("bool listo = true;", Declaracion("bool", "listo", N(True))),
        ("a = b;", Asignacion("a", V("b"))),
        ("print(a);", Print(V("a"))),
        ("while (a > 0) { }", While(BinOp(V("a"), ">", N(0)), [])),
        ("if (a) { print(a); }", If(V("a"), [Print(V("a"))])),
        ("if (a) { } else { a = 1; }", If(V("a"), [], [Asignacion("a", N(1))])),
    ],
)
def test_cada_tipo_de_sentencia_produce_su_nodo(codigo, esperado):
    # Arrange (en parámetros): un representante por cada regla de la gramática.
    # Act
    programa = parsear(codigo)

    # Assert
    assert programa.sentencias == [esperado]


def test_if_sin_else_deja_sino_en_none_y_con_else_vacio_deja_lista_vacia():
    # Arrange: dos particiones distintas que no deben confundirse.
    sin_else, con_else_vacio = "if (a) { }", "if (a) { } else { }"

    # Act
    nodo_sin_else = parsear(sin_else).sentencias[0]
    nodo_con_else = parsear(con_else_vacio).sentencias[0]

    # Assert
    assert nodo_sin_else.sino is None
    assert nodo_con_else.sino == []


@pytest.mark.parametrize("codigo", ["", "   \n", "// nada"])
def test_programa_vacio_es_valido(codigo):
    # Arrange: valor límite inferior, cero sentencias.
    # Act
    programa = parsear(codigo)

    # Assert
    assert programa == Programa([])


def test_programa_de_la_especificacion():
    # Arrange
    with open("ejemplos/validos/programa_especificacion.mini", encoding="utf-8") as archivo:
        codigo = archivo.read()

    # Act
    programa = parsear(codigo)

    # Assert
    tipos = [type(s).__name__ for s in programa.sentencias]
    assert tipos == ["Declaracion", "Declaracion", "Declaracion", "Asignacion", "If", "While"]
    asignacion = programa.sentencias[3]
    assert asignacion.valor == BinOp(
        V("a"), "+", BinOp(BinOp(V("b"), "*", BinOp(V("a"), "-", N(2))), "%", N(3))
    )


def test_bloques_anidados():
    # Arrange
    codigo = "while (i < 3) { if (i == 1) { print(i); } i = i + 1; }"

    # Act
    bucle = parsear(codigo).sentencias[0]

    # Assert
    assert bucle.cuerpo == [
        If(BinOp(V("i"), "==", N(1)), [Print(V("i"))]),
        Asignacion("i", BinOp(V("i"), "+", N(1))),
    ]


@pytest.mark.parametrize(
    ("codigo", "nombre"),
    [("int if = 5;", "if"), ("bool true;", "true"), ("float int = 1.0;", "int")],
)
def test_palabra_reservada_como_nombre_se_tolera_para_el_semantico(codigo, nombre):
    # Arrange: la FORMA es correcta; el significado lo juzga la fase semántica.
    # Act
    declaracion = parsear(codigo).sentencias[0]

    # Assert
    assert declaracion.nombre == nombre


# ---------------------------------------------------------------------------
# Precedencia y asociatividad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expresion", "arbol"),
    [
        # '*' más fuerte que '+'
        ("a + b * c", BinOp(V("a"), "+", BinOp(V("b"), "*", V("c")))),
        ("a * b + c", BinOp(BinOp(V("a"), "*", V("b")), "+", V("c"))),
        # '%' mismo nivel que '*': se agrupa a la izquierda
        ("a * b % c", BinOp(BinOp(V("a"), "*", V("b")), "%", V("c"))),
        ("a % b + c", BinOp(BinOp(V("a"), "%", V("b")), "+", V("c"))),
        # paréntesis cambian el orden y NO generan nodo propio
        ("(a + b) * c", BinOp(BinOp(V("a"), "+", V("b")), "*", V("c"))),
        ("((a))", V("a")),
        # asociatividad izquierda: (a - b) - c, no a - (b - c)
        ("a - b - c", BinOp(BinOp(V("a"), "-", V("b")), "-", V("c"))),
        ("a / b / c", BinOp(BinOp(V("a"), "/", V("b")), "/", V("c"))),
        # relacionales: la menor precedencia
        ("a + 1 < b * 2", BinOp(BinOp(V("a"), "+", N(1)), "<", BinOp(V("b"), "*", N(2)))),
        ("a != b", BinOp(V("a"), "!=", V("b"))),
    ],
)
def test_precedencia_y_asociatividad(expresion, arbol):
    # Arrange (en parámetros)
    # Act
    resultado = expresion_de(expresion)

    # Assert
    assert resultado == arbol


@pytest.mark.parametrize(
    ("expresion", "arbol"),
    [
        ("-5", N(-5)),  # literal negativo: se pliega a un solo Numero
        ("-2.5", N(-2.5)),
        ("--5", N(5)),
        ("-y", BinOp(N(0), "-", V("y"))),  # azúcar: -y  ==  0 - y
        ("-true", BinOp(N(0), "-", N(True))),  # no se pliega: lo juzga el semántico
        ("a - -1", BinOp(V("a"), "-", N(-1))),
        ("-2 * 3", BinOp(N(-2), "*", N(3))),  # el unario se aplica antes que '*'
    ],
)
def test_menos_unario(expresion, arbol):
    # Arrange (en parámetros)
    # Act
    resultado = expresion_de(expresion)

    # Assert
    assert resultado == arbol


# ---------------------------------------------------------------------------
# Errores sintácticos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "patron"),
    [
        ("int a = 5", "';' al final de la declaración"),
        ("a = 5", "';' al final de la asignación"),
        ("print(a)", "';' al final del print"),
        ("print a;", r"'\(' después de 'print'"),
        ("print(a;", r"'\)' para cerrar el print"),
        ("int = 5;", "nombre de variable después de 'int'"),
        ("a 5;", "'=' después de 'a'"),
        ("a = ;", "Se esperaba un valor"),
        ("print();", "Se esperaba un valor"),
        ("a = (1 + 2;", r"'\)' para cerrar el '\(' de la línea 1, columna 5"),
        ("if a > 0 { }", r"'\(' después de 'if'"),
        ("while (a > 0 { }", r"'\)' para cerrar la condición del 'while'"),
        ("if (a) print(a);", "'{' para abrir el bloque"),
        ("if (a) { a = 1;", "'}' para cerrar el bloque abierto en la línea 1"),
        ("else { }", "'else' sin un 'if'"),
        ("5;", "inicio de una sentencia"),
        ("}", "inicio de una sentencia"),
        ("a = 1 < 2 < 3;", "encadenar comparaciones"),
    ],
)
def test_errores_sintacticos_explican_que_se_esperaba(codigo, patron):
    # Arrange (en parámetros): un caso por cada forma de romper la gramática.
    # Act / Assert
    with pytest.raises(ErrorSintactico, match=patron) as info:
        parsear(codigo)
    assert info.value.sugerencia  # todo error trae una pista de corrección


@pytest.mark.parametrize(
    ("codigo", "linea", "columna"),
    [
        # ';' faltante y el siguiente token en OTRA línea: se señala justo después
        # del '5' (columna 9 + 1 carácter = 10), en la línea 1, no en la 2.
        ("int a = 5\nprint(a);", 1, 10),
        # Lexema de varios caracteres: '2.50' ocupa 4 columnas (9..12) → 13.
        ("int a = 2.50\nprint(a);", 1, 13),
        # Mismo caso en la MISMA línea: se señala el token inesperado ('print').
        ("int a = 5 print(a);", 1, 11),
        # Fin de archivo: justo después del último token.
        ("int a = 5", 1, 10),
        ("if (a) {\n  a = 1;\n", 2, 9),
        # Token inesperado al inicio absoluto: columna 1 (no 0).
        ("5;", 1, 1),
    ],
)
def test_posicion_del_error_sin_off_by_one(codigo, linea, columna):
    # Arrange (en parámetros)
    # Act
    with pytest.raises(ErrorSintactico) as info:
        parsear(codigo)

    # Assert
    assert (info.value.linea, info.value.columna) == (linea, columna)


# ---------------------------------------------------------------------------
# Valor límite: profundidad de anidamiento (protege la pila de recursión)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("niveles", "es_valido"),
    [
        (1, True),
        (PROFUNDIDAD_MAXIMA - 1, True),
        (PROFUNDIDAD_MAXIMA, True),  # ON point
        (PROFUNDIDAD_MAXIMA + 1, False),  # OFF point
    ],
)
def test_limite_de_parentesis_anidados(niveles, es_valido):
    # Arrange
    codigo = "x = " + "(" * niveles + "1" + ")" * niveles + ";"

    # Act / Assert
    if es_valido:
        assert expresion_de("(" * niveles + "1" + ")" * niveles) == N(1)
    else:
        with pytest.raises(ErrorSintactico, match="Anidamiento demasiado profundo"):
            parsear(codigo)


@pytest.mark.parametrize(
    ("niveles", "es_valido"),
    [(PROFUNDIDAD_MAXIMA, True), (PROFUNDIDAD_MAXIMA + 1, False)],
)
def test_limite_de_bloques_anidados(niveles, es_valido):
    # Arrange
    codigo = "while (a) { " * niveles + "}" * niveles

    # Act / Assert
    if es_valido:
        assert isinstance(parsear(codigo).sentencias[0], While)
    else:
        with pytest.raises(ErrorSintactico, match="Anidamiento demasiado profundo"):
            parsear(codigo)


def test_la_profundidad_se_libera_al_cerrar_cada_nivel():
    # Arrange: muchos paréntesis en SECUENCIA (no anidados) no deben acumularse.
    # Si _salir() no restara, esto fallaría al pasar de 100 grupos.
    codigo = "x = " + " + ".join(["(1)"] * (PROFUNDIDAD_MAXIMA * 2)) + ";"

    # Act
    programa = parsear(codigo)

    # Assert
    assert len(programa.sentencias) == 1


# ---------------------------------------------------------------------------
# Posiciones de los nodos y contrato del Parser
# ---------------------------------------------------------------------------


def test_los_nodos_guardan_la_posicion_de_su_token_principal():
    # Arrange
    codigo = "int a;\na = b * 2;"

    # Act
    asignacion = parsear(codigo).sentencias[1]

    # Assert
    assert (asignacion.linea, asignacion.columna) == (2, 1)
    assert (asignacion.valor.linea, asignacion.valor.columna) == (2, 7)  # el '*'
    assert (asignacion.valor.derecha.linea, asignacion.valor.derecha.columna) == (2, 9)


def test_parser_exige_tokens_terminados_en_eof():
    # Arrange: tokens sin EOF (contrato roto por quien llama).
    tokens = tokenizar("a = 1;")[:-1]

    # Act / Assert
    with pytest.raises(ValueError, match="EOF"):
        Parser(tokens)
