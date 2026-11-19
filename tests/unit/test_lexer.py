"""Pruebas unitarias del analizador léxico.

Técnicas del curso que se demuestran aquí:
    * Patrón AAA (Arrange / Act / Assert) en todas las pruebas.
    * Partición de equivalencia: clases de entradas que el lexer trata igual
      (identificadores válidos, inválidos, palabras reservadas...).
    * Valores límite (on/off points): longitud 31 vs 32 de un identificador.
    * Off-by-one: columnas 1-based, reinicio de columna tras salto de línea.
    * DRY: ``@pytest.mark.parametrize`` en lugar de copiar pruebas (WET).
"""

import pytest

from minicompilador.errores import ErrorLexico
from minicompilador.lexer import (
    LONGITUD_MAXIMA_IDENTIFICADOR,
    TipoToken,
    Token,
    tokenizar,
)

T = TipoToken  # alias corto para que las tablas de parametrize sean legibles


def tipos_sin_eof(codigo: str) -> list[TipoToken]:
    """Helper: tipos de token del código, sin el EOF final."""
    return [token.tipo for token in tokenizar(codigo)[:-1]]


# ---------------------------------------------------------------------------
# Casos felices
# ---------------------------------------------------------------------------


def test_tokeniza_una_declaracion_con_tipo_valor_y_posicion():
    # Arrange
    codigo = "int a = 5;"

    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert tokens == [
        Token(T.TIPO, "int", 1, 1),
        Token(T.IDENTIFICADOR, "a", 1, 5),
        Token(T.ASIGNAR, "=", 1, 7),
        Token(T.ENTERO, 5, 1, 9),
        Token(T.PUNTO_Y_COMA, ";", 1, 10),
        Token(T.EOF, "", 1, 11),
    ]


@pytest.mark.parametrize(
    ("palabra", "tipo", "valor"),
    [
        ("int", T.TIPO, "int"),
        ("float", T.TIPO, "float"),
        ("bool", T.TIPO, "bool"),
        ("if", T.IF, "if"),
        ("else", T.ELSE, "else"),
        ("while", T.WHILE, "while"),
        ("print", T.PRINT, "print"),
        ("true", T.BOOLEANO, True),
        ("false", T.BOOLEANO, False),
    ],
)
def test_reconoce_cada_palabra_reservada(palabra, tipo, valor):
    # Arrange: partición "palabras reservadas" (un representante por cada una).
    codigo = palabra

    # Act
    token = tokenizar(codigo)[0]

    # Assert
    assert (token.tipo, token.valor) == (tipo, valor)


@pytest.mark.parametrize(
    "palabra",
    ["If", "WHILE", "Print", "True", "integer", "iff", "int_"],
)
def test_variantes_de_palabras_reservadas_son_identificadores(palabra):
    # Arrange: partición "casi reservadas" (mayúsculas, prefijos, sufijos).
    # Prueba que la búsqueda es exacta y sensible a mayúsculas.
    codigo = palabra

    # Act
    token = tokenizar(codigo)[0]

    # Assert
    assert token.tipo is T.IDENTIFICADOR
    assert token.valor == palabra


@pytest.mark.parametrize(
    ("operador", "tipo"),
    [
        ("+", T.MAS),
        ("-", T.MENOS),
        ("*", T.POR),
        ("/", T.DIVISION),
        ("%", T.MODULO),
        ("<", T.MENOR),
        (">", T.MAYOR),
        ("<=", T.MENOR_IGUAL),
        (">=", T.MAYOR_IGUAL),
        ("==", T.IGUAL_IGUAL),
        ("!=", T.DISTINTO),
        ("=", T.ASIGNAR),
        ("(", T.PAREN_IZQ),
        (")", T.PAREN_DER),
        ("{", T.LLAVE_IZQ),
        ("}", T.LLAVE_DER),
        (";", T.PUNTO_Y_COMA),
    ],
)
def test_reconoce_cada_operador_y_delimitador(operador, tipo):
    # Arrange: el operando a la izquierda hace que '%' sea módulo válido.
    codigo = f"a {operador}"

    # Act
    token = tokenizar(codigo)[1]

    # Assert
    assert token.tipo is tipo
    assert token.valor == operador


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        # Maximal munch: dos caracteres forman UN token.
        ("a<=b", [T.IDENTIFICADOR, T.MENOR_IGUAL, T.IDENTIFICADOR]),
        ("a==b", [T.IDENTIFICADOR, T.IGUAL_IGUAL, T.IDENTIFICADOR]),
        # Con espacio en medio ya son dos tokens distintos.
        ("a< =b", [T.IDENTIFICADOR, T.MENOR, T.ASIGNAR, T.IDENTIFICADOR]),
        # '===' = '==' seguido de '=' (el lexer no juzga, eso es del parser).
        ("===", [T.IGUAL_IGUAL, T.ASIGNAR]),
    ],
)
def test_aplica_coincidencia_mas_larga_en_operadores(codigo, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = tipos_sin_eof(codigo)

    # Assert
    assert resultado == esperado


def test_tokeniza_el_programa_de_la_especificacion_sin_errores():
    # Arrange
    codigo = (
        "int a = 5;\n"
        "float b = 2.5;\n"
        "int c;\n"
        "c = a + b * (a - 2) % 3;\n"
        "if (c > 10) {\n"
        "    print(c);\n"
        "} else {\n"
        "    c = c / 2;\n"
        "    print(c);\n"
        "}\n"
        "while (a > 0) {\n"
        "    a = a - 1;\n"
        "}\n"
    )

    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert len(tokens) == 69  # 68 tokens + EOF (contados a mano por línea)
    assert tokens[-1] == Token(T.EOF, "", 14, 1)
    # El '%' de la línea 4 va tras ')' => es el operador módulo.
    modulo = next(t for t in tokens if t.tipo is T.MODULO)
    assert (modulo.linea, modulo.columna) == (4, 21)


# ---------------------------------------------------------------------------
# Números: partición de equivalencia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "tipo", "valor"),
    [
        ("0", T.ENTERO, 0),  # valor límite inferior: un solo dígito
        ("42", T.ENTERO, 42),
        ("007", T.ENTERO, 7),  # ceros a la izquierda se aceptan
        ("2.5", T.REAL, 2.5),
        ("0.0", T.REAL, 0.0),
        ("10.25", T.REAL, 10.25),
    ],
)
def test_numeros_validos_se_convierten_a_su_tipo_python(codigo, tipo, valor):
    # Arrange (en parámetros)
    # Act
    token = tokenizar(codigo)[0]

    # Assert
    assert token.tipo is tipo
    assert token.valor == valor
    assert type(token.valor) is type(valor)


@pytest.mark.parametrize(
    ("codigo", "patron"),
    [
        ("x = 2.;", r"Número real incompleto '2\.'"),
        ("x = 2.5.3;", "más de un punto decimal"),
        ("x = 5abc;", "no puede empezar con un dígito"),
        ("x = 2.5e;", "no puede empezar con un dígito"),
        ("x = .5;", r"Carácter no reconocido '\.'"),
    ],
)
def test_numeros_mal_formados_producen_error_lexico(codigo, patron):
    # Arrange (en parámetros): partición "números inválidos".
    # Act / Assert
    with pytest.raises(ErrorLexico, match=patron):
        tokenizar(codigo)


# ---------------------------------------------------------------------------
# Identificadores: partición de equivalencia + valores límite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nombre",
    ["a", "_", "_privado", "contador_1", "x9", "CamelCase", "a_b_c_d"],
)
def test_identificadores_validos(nombre):
    # Arrange: partición válida [A-Za-z_][A-Za-z0-9_]*
    codigo = nombre

    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert tokens[0] == Token(T.IDENTIFICADOR, nombre, 1, 1)
    assert len(tokens) == 2  # identificador + EOF: no se partió en dos


@pytest.mark.parametrize(
    ("longitud", "es_valido"),
    [
        (1, True),  # límite inferior
        (30, True),  # justo antes del límite
        (31, True),  # ON point: el valor límite exacto es válido
        (32, False),  # OFF point: el primer valor fuera del límite
        (100, False),  # representante de la partición inválida
    ],
)
def test_valor_limite_longitud_de_identificador(longitud, es_valido):
    # Arrange: frontera en 31 caracteres (LONGITUD_MAXIMA_IDENTIFICADOR).
    assert LONGITUD_MAXIMA_IDENTIFICADOR == 31
    nombre = "v" * longitud
    codigo = f"int {nombre} = 1;"

    # Act / Assert
    if es_valido:
        tokens = tokenizar(codigo)
        assert tokens[1] == Token(T.IDENTIFICADOR, nombre, 1, 5)
    else:
        with pytest.raises(ErrorLexico, match=f"tiene {longitud} caracteres") as info:
            tokenizar(codigo)
        # El error señala el INICIO del identificador, no su final.
        assert (info.value.linea, info.value.columna) == (1, 5)


# ---------------------------------------------------------------------------
# El caso '%': operador módulo vs. identificador ilegal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "columna"),
    [
        ("%a = 5;", 1),  # caso de la especificación
        ("c = %a + 1;", 5),  # tras '=' no hay operando
        ("c = (%t1);", 6),  # '%t' es el prefijo de las temporales internas
        ("int x;\n%_y = 2;", 1),  # en la línea 2, columna 1 (off-by-one)
    ],
)
def test_porcentaje_pegado_a_nombre_sin_operando_previo_es_error(codigo, columna):
    # Arrange (en parámetros)
    # Act / Assert
    with pytest.raises(ErrorLexico, match="no es un identificador válido") as info:
        tokenizar(codigo)
    assert info.value.columna == columna
    assert info.value.fase == "lexico"


@pytest.mark.parametrize(
    "codigo",
    ["a%b", "a % b", "(a)%b", "5%a", "2.5%x", "true%a"],
)
def test_porcentaje_despues_de_un_operando_es_modulo(codigo):
    # Arrange: partición "módulo válido" (anterior = identificador, número,
    # booleano o ')').
    # Act
    resultado = tipos_sin_eof(codigo)

    # Assert
    assert T.MODULO in resultado
    assert resultado[-1] is T.IDENTIFICADOR


def test_error_de_modulo_explica_por_que_y_como_corregir():
    # Arrange
    codigo = "%a = 5;"

    # Act
    with pytest.raises(ErrorLexico) as info:
        tokenizar(codigo)
    datos = info.value.a_dict()

    # Assert
    assert datos["tipo"] == "ErrorLexico"
    assert "operador módulo" in datos["mensaje"]
    assert "'a'" in datos["sugerencia"]


# ---------------------------------------------------------------------------
# Caracteres inválidos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "caracter", "pista"),
    [
        ("int a = @;", "@", "Elimina el carácter"),
        ("if (!a) {}", "!", "usa '!='"),
        ("a = b & c;", "&", "if anidados"),
        ("a = b | c;", "|", "if anidados"),
        ('print("hola");', '"', "no tiene cadenas"),
        ("int año = 1;", "ñ", "ASCII"),
        ("x = 2²;", "²", "ASCII"),  # isdigit('²') es True: por eso usamos rangos ASCII
    ],
)
def test_caracteres_no_reconocidos_dan_pista_especifica(codigo, caracter, pista):
    # Arrange (en parámetros)
    # Act / Assert
    with pytest.raises(ErrorLexico, match=f"Carácter no reconocido '{caracter}'") as info:
        tokenizar(codigo)
    assert pista in info.value.sugerencia


# ---------------------------------------------------------------------------
# Posiciones: errores off-by-one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "linea", "columna"),
    [
        ("@", 1, 1),  # primer carácter: columna 1, no 0
        ("int a = @;", 1, 9),
        ("\n@", 2, 1),  # tras '\n' la columna se reinicia a 1
        ("int a;\n\n   @", 3, 4),  # líneas vacías también cuentan
        ("\t@", 1, 2),  # un tab cuenta como una columna
        ("// comentario @\n@", 2, 1),  # el '@' del comentario se ignora
    ],
)
def test_error_reporta_linea_y_columna_exactas(codigo, linea, columna):
    # Arrange (en parámetros)
    # Act
    with pytest.raises(ErrorLexico) as info:
        tokenizar(codigo)

    # Assert
    assert (info.value.linea, info.value.columna) == (linea, columna)


def test_token_que_sigue_a_un_operador_doble_tiene_columna_correcta():
    # Arrange: tras consumir 2 caracteres la columna debe avanzar 2, no 1.
    codigo = "a<=b"

    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert [t.columna for t in tokens] == [1, 2, 4, 5]


def test_columna_del_ultimo_caracter_y_del_eof():
    # Arrange: valor límite del recorrido (último carácter del texto).
    codigo = "a\nbb"

    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert tokens[1] == Token(T.IDENTIFICADOR, "bb", 2, 1)
    assert tokens[2] == Token(T.EOF, "", 2, 3)


@pytest.mark.parametrize(
    "codigo",
    ["", "   ", "\n\n", "// solo un comentario"],
)
def test_codigo_vacio_o_solo_espacios_produce_solo_eof(codigo):
    # Arrange: partición "sin contenido significativo".
    # Act
    tokens = tokenizar(codigo)

    # Assert
    assert len(tokens) == 1
    assert tokens[0].tipo is T.EOF


# ---------------------------------------------------------------------------
# Comentarios y serialización
# ---------------------------------------------------------------------------


def test_comentario_hasta_fin_de_linea_y_division_simple():
    # Arrange
    codigo = "a = b / 2; // divide b\nprint(a);"

    # Act
    resultado = tipos_sin_eof(codigo)

    # Assert
    assert resultado == [
        T.IDENTIFICADOR, T.ASIGNAR, T.IDENTIFICADOR, T.DIVISION, T.ENTERO, T.PUNTO_Y_COMA,
        T.PRINT, T.PAREN_IZQ, T.IDENTIFICADOR, T.PAREN_DER, T.PUNTO_Y_COMA,
    ]  # fmt: skip


def test_token_a_dict_es_serializable_a_json():
    # Arrange
    token = tokenizar("2.5")[0]

    # Act
    datos = token.a_dict()

    # Assert
    assert datos == {"tipo": "REAL", "valor": 2.5, "linea": 1, "columna": 1}


@pytest.mark.parametrize(
    ("codigo", "es_valido"),
    [
        ("2147483647", True),  # on point: el int más grande de 32 bits
        ("2147483648", False),  # off point: uno más ya no cabe
        ("1" + "0" * 308 + ".0", True),  # 1e308 es un float finito
        ("9" * 400 + ".0", False),  # se convierte en infinito
    ],
)
def test_valor_limite_del_rango_de_literales(codigo, es_valido):
    # Arrange (en parámetros)
    # Act / Assert
    if es_valido:
        assert tokenizar(codigo)[0].lexema == codigo
    else:
        with pytest.raises(ErrorLexico, match="fuera de rango"):
            tokenizar(codigo)
