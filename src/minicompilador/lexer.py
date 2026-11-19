"""Fase 1 - Análisis léxico (escáner).

Convierte el texto fuente en una lista de *tokens*: las "palabras" del lenguaje.
Cada token guarda su tipo, su valor, y la línea/columna donde empieza (1-based),
para que las fases siguientes puedan señalar errores con precisión.

Algoritmo (explicable en la sustentación):
    Recorremos el texto con un puntero ``_pos``. En cada paso miramos el carácter
    actual y decidimos qué tipo de token *puede* empezar ahí:

        espacio/salto  -> se ignora (solo actualiza línea/columna)
        '//'           -> comentario hasta fin de línea, se ignora
        dígito         -> número entero o real
        letra o '_'    -> identificador o palabra reservada
        '%'            -> operador módulo (con validación de contexto)
        otro símbolo   -> operador o delimitador (primero probamos 2 caracteres)

    Es un autómata finito escrito a mano: no usamos expresiones regulares ni
    generadores (PLY, Lark...) para que cada decisión sea visible y probable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from minicompilador.errores import ErrorLexico
from minicompilador.operaciones import ENTERO_MAXIMO

#: Límite de longitud de identificadores (valor límite clave para las pruebas:
#: 31 caracteres = válido "on point", 32 = inválido "off point").
LONGITUD_MAXIMA_IDENTIFICADOR = 31


class TipoToken(StrEnum):
    """Categorías de token. Al ser ``StrEnum`` se serializan a JSON como texto."""

    # Literales e identificadores
    ENTERO = "ENTERO"
    REAL = "REAL"
    BOOLEANO = "BOOLEANO"
    IDENTIFICADOR = "IDENTIFICADOR"
    # Palabras reservadas
    TIPO = "TIPO"  # int | float | bool (el valor dice cuál)
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    PRINT = "PRINT"
    # Operadores aritméticos (mayor precedencia: * / %)
    MAS = "MAS"
    MENOS = "MENOS"
    POR = "POR"
    DIVISION = "DIVISION"
    MODULO = "MODULO"
    # Operadores relacionales (menor precedencia)
    MENOR = "MENOR"
    MAYOR = "MAYOR"
    MENOR_IGUAL = "MENOR_IGUAL"
    MAYOR_IGUAL = "MAYOR_IGUAL"
    IGUAL_IGUAL = "IGUAL_IGUAL"
    DISTINTO = "DISTINTO"
    # Asignación y delimitadores
    ASIGNAR = "ASIGNAR"
    PAREN_IZQ = "PAREN_IZQ"
    PAREN_DER = "PAREN_DER"
    LLAVE_IZQ = "LLAVE_IZQ"
    LLAVE_DER = "LLAVE_DER"
    PUNTO_Y_COMA = "PUNTO_Y_COMA"
    # Marca de fin de archivo: evita que el parser tenga que preguntar
    # "¿hay más tokens?" en cada paso (simplifica y evita off-by-one).
    EOF = "EOF"


#: Palabras reservadas -> (tipo de token, valor). Son sensibles a mayúsculas:
#: ``If`` es un identificador normal, ``if`` es reservada.
PALABRAS_RESERVADAS: dict[str, tuple[TipoToken, Any]] = {
    "int": (TipoToken.TIPO, "int"),
    "float": (TipoToken.TIPO, "float"),
    "bool": (TipoToken.TIPO, "bool"),
    "if": (TipoToken.IF, "if"),
    "else": (TipoToken.ELSE, "else"),
    "while": (TipoToken.WHILE, "while"),
    "print": (TipoToken.PRINT, "print"),
    "true": (TipoToken.BOOLEANO, True),
    "false": (TipoToken.BOOLEANO, False),
}

#: Operadores de dos caracteres. Se prueban ANTES que los de uno
#: (regla de la "coincidencia más larga" o *maximal munch*): así ``<=`` es un
#: solo token y no ``<`` seguido de ``=``.
OPERADORES_DOBLES: dict[str, TipoToken] = {
    "<=": TipoToken.MENOR_IGUAL,
    ">=": TipoToken.MAYOR_IGUAL,
    "==": TipoToken.IGUAL_IGUAL,
    "!=": TipoToken.DISTINTO,
}

OPERADORES_SIMPLES: dict[str, TipoToken] = {
    "+": TipoToken.MAS,
    "-": TipoToken.MENOS,
    "*": TipoToken.POR,
    "/": TipoToken.DIVISION,
    "<": TipoToken.MENOR,
    ">": TipoToken.MAYOR,
    "=": TipoToken.ASIGNAR,
    "(": TipoToken.PAREN_IZQ,
    ")": TipoToken.PAREN_DER,
    "{": TipoToken.LLAVE_IZQ,
    "}": TipoToken.LLAVE_DER,
    ";": TipoToken.PUNTO_Y_COMA,
}

#: Tokens que representan un *operando* (algo con valor). Si un ``%`` aparece
#: justo después de uno de ellos, es el operador módulo (``a%b``).
TOKENS_OPERANDO = frozenset(
    {
        TipoToken.IDENTIFICADOR,
        TipoToken.ENTERO,
        TipoToken.REAL,
        TipoToken.BOOLEANO,
        TipoToken.PAREN_DER,
    }
)


@dataclass(frozen=True, slots=True)
class Token:
    """Unidad léxica. Es inmutable (``frozen``): ninguna fase posterior la altera.

    Attributes:
        tipo: categoría del token.
        valor: ``int``/``float``/``bool`` para literales, texto para el resto.
        linea: línea donde EMPIEZA el token (1-based).
        columna: columna donde EMPIEZA el token (1-based).
        lexema: texto original tal como se escribió (``"007"`` para el valor 7).
            El parser lo usa para calcular dónde TERMINA un token y así señalar
            con precisión un ``;`` faltante. ``compare=False``: dos tokens son
            iguales si coinciden tipo, valor y posición.
    """

    tipo: TipoToken
    valor: Any
    linea: int
    columna: int
    lexema: str = field(default="", compare=False)

    def a_dict(self) -> dict[str, Any]:
        """Forma serializable usada en la sección ``tokens`` del reporte."""
        return {
            "tipo": self.tipo.value,
            "valor": self.valor,
            "linea": self.linea,
            "columna": self.columna,
        }


# --- Clasificadores de caracteres ------------------------------------------
# Usamos rangos ASCII explícitos a propósito: ``str.isdigit()`` acepta '²' y
# ``str.isalpha()`` acepta 'ñ', que Mini NO permite. Ser explícito evita esos
# casos borde (se prueban en tests/unit/test_lexer.py).


def es_digito(caracter: str) -> bool:
    """``True`` si es un dígito ASCII 0-9."""
    return "0" <= caracter <= "9"


def es_inicio_identificador(caracter: str) -> bool:
    """``True`` si puede iniciar un identificador: ``[A-Za-z_]``."""
    return caracter == "_" or "a" <= caracter <= "z" or "A" <= caracter <= "Z"


def es_parte_identificador(caracter: str) -> bool:
    """``True`` si puede continuar un identificador: ``[A-Za-z0-9_]``."""
    return es_inicio_identificador(caracter) or es_digito(caracter)


class Lexer:
    """Escáner manual del lenguaje Mini.

    Uso::

        tokens = Lexer("int a = 5;").tokenizar()
    """

    def __init__(self, codigo: str) -> None:
        self._codigo = codigo
        self._pos = 0  # índice del carácter actual dentro de ``_codigo``
        self._linea = 1  # 1-based: así lo cuentan los editores de texto
        self._columna = 1
        self._tokens: list[Token] = []

    # ------------------------------------------------------------------ API

    def tokenizar(self) -> list[Token]:
        """Recorre todo el código y devuelve los tokens terminados en ``EOF``.

        Raises:
            ErrorLexico: en el PRIMER carácter o palabra inválida (el compilador
                se detiene en la fase donde falla).
        """
        while not self._fin():
            caracter = self._actual()
            if caracter in " \t\r\n":
                self._avanzar()
            elif caracter == "/" and self._siguiente() == "/":
                self._saltar_comentario()
            elif es_digito(caracter):
                self._leer_numero()
            elif es_inicio_identificador(caracter):
                self._leer_identificador()
            elif caracter == "%":
                self._leer_modulo()
            else:
                self._leer_operador()
        self._tokens.append(Token(TipoToken.EOF, "", self._linea, self._columna))
        return self._tokens

    # ------------------------------------------------- navegación del texto

    def _fin(self) -> bool:
        return self._pos >= len(self._codigo)

    def _actual(self) -> str:
        """Carácter actual o ``""`` si ya terminamos (evita IndexError)."""
        return self._codigo[self._pos] if not self._fin() else ""

    def _siguiente(self) -> str:
        """Mira UN carácter adelante sin consumirlo (*lookahead*)."""
        indice = self._pos + 1
        return self._codigo[indice] if indice < len(self._codigo) else ""

    def _avanzar(self) -> str:
        """Consume un carácter y actualiza línea/columna.

        Este es el único lugar donde cambian línea y columna: centralizarlo
        evita errores off-by-one dispersos por el código.
        """
        caracter = self._codigo[self._pos]
        self._pos += 1
        if caracter == "\n":
            self._linea += 1
            self._columna = 1
        else:
            self._columna += 1
        return caracter

    def _consumir_mientras(self, condicion: Callable[[str], bool]) -> str:
        inicio = self._pos
        while not self._fin() and condicion(self._actual()):
            self._avanzar()
        return self._codigo[inicio : self._pos]

    def _agregar(
        self, tipo: TipoToken, valor: Any, linea: int, columna: int, lexema: str | None = None
    ) -> None:
        # Si no se indica lexema, el valor ya es el texto original (operadores).
        texto = str(valor) if lexema is None else lexema
        self._tokens.append(Token(tipo, valor, linea, columna, texto))

    # ----------------------------------------------------------- reconocedores

    def _saltar_comentario(self) -> None:
        """``// ...`` hasta el fin de la línea. El ``\\n`` lo procesa el bucle principal."""
        self._consumir_mientras(lambda c: c != "\n")

    def _leer_numero(self) -> None:
        """Reconoce ``ENTERO`` (``42``) o ``REAL`` (``2.5``)."""
        linea, columna = self._linea, self._columna
        texto = self._consumir_mientras(es_digito)

        if self._actual() == ".":
            if not es_digito(self._siguiente()):
                raise ErrorLexico(
                    f"Número real incompleto '{texto}.': después del punto decimal "
                    "debe venir al menos un dígito.",
                    linea,
                    columna,
                    sugerencia=f"Escribe '{texto}.0' o '{texto}'.",
                )
            texto += self._avanzar()  # el punto
            texto += self._consumir_mientras(es_digito)
            if self._actual() == ".":
                raise ErrorLexico(
                    f"El número '{texto}.' tiene más de un punto decimal.",
                    linea,
                    columna,
                    sugerencia="Un número real solo puede tener un punto, por ejemplo 2.5.",
                )
            self._verificar_fin_de_numero(texto, linea, columna)
            valor: int | float = float(texto)
            tipo = TipoToken.REAL
        else:
            self._verificar_fin_de_numero(texto, linea, columna)
            valor, tipo = int(texto), TipoToken.ENTERO

        # Valor límite: 2147483647 es el último int válido; 2147483648 ya no.
        # (El lexer solo ve literales sin signo; el '-' es un operador aparte.)
        if (tipo is TipoToken.ENTERO and valor > ENTERO_MAXIMO) or valor == float("inf"):
            raise ErrorLexico(
                f"El número '{texto}' está fuera de rango: un int de Mini llega hasta "
                f"{ENTERO_MAXIMO} y un float debe ser finito.",
                linea,
                columna,
                sugerencia="Usa un número más pequeño.",
            )
        self._agregar(tipo, valor, linea, columna, texto)

    def _verificar_fin_de_numero(self, texto: str, linea: int, columna: int) -> None:
        """Un número pegado a una letra (``5abc``) no es número ni identificador válido."""
        if es_inicio_identificador(self._actual()):
            resto = self._consumir_mientras(es_parte_identificador)
            raise ErrorLexico(
                f"'{texto}{resto}' no es válido: un identificador no puede empezar con un dígito.",
                linea,
                columna,
                sugerencia=f"Empieza el nombre con una letra o '_', por ejemplo 'v{texto}{resto}'.",
            )

    def _leer_identificador(self) -> None:
        """Reconoce identificadores y palabras reservadas: ``[A-Za-z_][A-Za-z0-9_]*``."""
        linea, columna = self._linea, self._columna
        texto = self._consumir_mientras(es_parte_identificador)

        # Valor límite: 31 es válido (on point), 32 ya es inválido (off point).
        if len(texto) > LONGITUD_MAXIMA_IDENTIFICADOR:
            raise ErrorLexico(
                f"El identificador '{texto[:10]}...' tiene {len(texto)} caracteres; "
                f"el máximo permitido es {LONGITUD_MAXIMA_IDENTIFICADOR}.",
                linea,
                columna,
                sugerencia="Usa un nombre más corto pero descriptivo.",
            )

        if texto in PALABRAS_RESERVADAS:
            tipo, valor = PALABRAS_RESERVADAS[texto]
            self._agregar(tipo, valor, linea, columna, texto)
        else:
            self._agregar(TipoToken.IDENTIFICADOR, texto, linea, columna)

    def _leer_modulo(self) -> None:
        """Reconoce ``%`` como operador módulo y rechaza ``%a`` como identificador.

        ¿Por qué validar el contexto? En Mini, ``%`` es SOLO el operador módulo.
        Además, el compilador reserva el prefijo ``%t`` para sus variables
        temporales (``%t1``, ``%t2``...). Si el usuario pudiera escribir ``%t1``,
        sus variables chocarían con las del compilador.

        Regla: si ``%`` va pegado a una letra y el token anterior NO es un
        operando, el usuario está intentando escribir un identificador:
            ``a%b``  -> válido (anterior = IDENTIFICADOR, es módulo)
            ``%a = 5`` -> error (no hay operando a la izquierda)
        """
        linea, columna = self._linea, self._columna
        self._avanzar()  # consume '%'

        anterior = self._tokens[-1].tipo if self._tokens else None
        if es_inicio_identificador(self._actual()) and anterior not in TOKENS_OPERANDO:
            nombre = self._consumir_mientras(es_parte_identificador)
            raise ErrorLexico(
                f"'%{nombre}' no es un identificador válido: '%' es solo el operador "
                "módulo y el prefijo '%' está reservado para las temporales del compilador.",
                linea,
                columna,
                sugerencia=f"Usa un nombre que empiece con letra o '_', por ejemplo '{nombre}'.",
            )
        self._agregar(TipoToken.MODULO, "%", linea, columna)

    def _leer_operador(self) -> None:
        """Operadores y delimitadores; primero 2 caracteres (*maximal munch*)."""
        linea, columna = self._linea, self._columna
        caracter = self._actual()
        doble = caracter + self._siguiente()

        if doble in OPERADORES_DOBLES:
            self._avanzar()
            self._avanzar()
            self._agregar(OPERADORES_DOBLES[doble], doble, linea, columna)
        elif caracter in OPERADORES_SIMPLES:
            self._avanzar()
            self._agregar(OPERADORES_SIMPLES[caracter], caracter, linea, columna)
        else:
            raise ErrorLexico(
                f"Carácter no reconocido '{caracter}'.",
                linea,
                columna,
                sugerencia=_sugerencia_para(caracter),
            )


def _sugerencia_para(caracter: str) -> str:
    """Pista específica para los caracteres inválidos más frecuentes."""
    pistas = {
        "!": "Mini no tiene negación '!'; para 'distinto de' usa '!='.",
        ".": "Un número real debe empezar con dígito: escribe 0.5 en lugar de .5.",
        "&": "Mini no tiene operadores lógicos '&&'; usa if anidados.",
        "|": "Mini no tiene operadores lógicos '||'; usa if anidados.",
        '"': "Mini no tiene cadenas de texto; print solo acepta expresiones numéricas.",
    }
    if caracter in pistas:
        return pistas[caracter]
    if not caracter.isascii():
        return "Mini solo acepta caracteres ASCII (sin tildes ni 'ñ') en el código."
    return "Elimina el carácter o revisa la especificación del lenguaje Mini."


def tokenizar(codigo: str) -> list[Token]:
    """Atajo funcional: ``tokenizar(codigo)`` == ``Lexer(codigo).tokenizar()``."""
    return Lexer(codigo).tokenizar()
