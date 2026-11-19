"""Fase 2 - Análisis sintáctico: parser descendente recursivo.

Recibe la lista de tokens y construye el AST. "Descendente recursivo" significa
que hay UNA función por cada regla de la gramática, y las funciones se llaman
entre sí igual que las reglas se mencionan entre sí.

Gramática de Mini (EBNF):

    programa     → sentencia* EOF
    sentencia    → declaracion | asignacion | if | while | print
    declaracion  → TIPO nombre ( "=" expresion )? ";"
    asignacion   → IDENTIFICADOR "=" expresion ";"
    if           → "if" "(" expresion ")" bloque ( "else" bloque )?
    while        → "while" "(" expresion ")" bloque
    print        → "print" "(" expresion ")" ";"
    bloque       → "{" sentencia* "}"

    expresion    → comparacion
    comparacion  → suma ( ("<"|">"|"<="|">="|"=="|"!=") suma )?   ← menor precedencia
    suma         → termino ( ("+"|"-") termino )*
    termino      → factor ( ("*"|"/"|"%") factor )*                ← mayor precedencia
    factor       → NUMERO | BOOLEANO | IDENTIFICADOR | "(" expresion ")" | "-" factor

¿Cómo se logra la precedencia? Cada nivel llama al nivel de MAYOR precedencia
para obtener sus operandos. ``suma`` pide ``termino``s, así que en ``a + b * c``
la multiplicación queda "más abajo" en el árbol y se evalúa primero.

¿Cómo se logra la asociatividad izquierda? Con un bucle ``while`` que va
envolviendo el resultado: ``a - b - c`` → ``(a - b) - c``.
"""

from __future__ import annotations

from minicompilador.ast_nodos import (
    Asignacion,
    BinOp,
    Declaracion,
    If,
    Nodo,
    Numero,
    Print,
    Programa,
    Variable,
    While,
)
from minicompilador.errores import ErrorSintactico
from minicompilador.lexer import TipoToken, Token, tokenizar

T = TipoToken

#: Máximo anidamiento de paréntesis, menos unarios y bloques. Cada nivel
#: consume ~5 llamadas recursivas de Python; sin este límite un programa como
#: "((((...))))" provocaría un RecursionError en lugar de un error amigable.
#: Valor límite para las pruebas: 100 niveles = válido, 101 = error.
PROFUNDIDAD_MAXIMA = 100

OPERADORES_RELACIONALES = frozenset(
    {T.MENOR, T.MAYOR, T.MENOR_IGUAL, T.MAYOR_IGUAL, T.IGUAL_IGUAL, T.DISTINTO}
)
OPERADORES_SUMA = frozenset({T.MAS, T.MENOS})
OPERADORES_PRODUCTO = frozenset({T.POR, T.DIVISION, T.MODULO})

#: Palabras reservadas que el parser TOLERA como nombre en una declaración
#: (``int if = 5;``). No es un error sintáctico: la frase tiene la forma
#: correcta. La fase semántica es la que detecta y explica el problema.
PALABRAS_RESERVADAS_COMO_NOMBRE = frozenset({T.TIPO, T.IF, T.ELSE, T.WHILE, T.PRINT, T.BOOLEANO})


class Parser:
    """Parser descendente recursivo de Mini.

    Uso::

        programa = Parser(tokenizar("int a = 5;")).parsear()
    """

    def __init__(self, tokens: list[Token]) -> None:
        if not tokens or tokens[-1].tipo is not T.EOF:
            raise ValueError("La lista de tokens debe terminar en EOF (usa el lexer).")
        self._tokens = tokens
        self._pos = 0
        self._profundidad = 0

    # ------------------------------------------------------------------ API

    def parsear(self) -> Programa:
        """programa → sentencia* EOF"""
        sentencias = []
        while not self._ver(T.EOF):
            sentencias.append(self._sentencia())
        return Programa(sentencias, linea=1, columna=1)

    # ------------------------------------------------------ manejo de tokens

    def _actual(self) -> Token:
        return self._tokens[self._pos]

    def _anterior(self) -> Token:
        return self._tokens[self._pos - 1]

    def _ver(self, *tipos: TipoToken) -> bool:
        """¿El token actual es de alguno de estos tipos? (no consume)."""
        return self._actual().tipo in tipos

    def _avanzar(self) -> Token:
        # Invariante: solo se llama tras verificar el token con _ver(), y ninguna
        # regla consume el EOF, así que _pos nunca se sale de la lista.
        token = self._actual()
        self._pos += 1
        return token

    def _consumir(self, tipo: TipoToken, esperado: str, sugerencia: str | None = None) -> Token:
        """Consume un token del tipo indicado o lanza ``ErrorSintactico``."""
        if self._ver(tipo):
            return self._avanzar()
        raise self._error(
            f"Se esperaba {esperado} pero se encontró {self._describir()}.", sugerencia
        )

    def _describir(self, token: Token | None = None) -> str:
        token = token or self._actual()
        return "el fin del archivo" if token.tipo is T.EOF else f"'{token.lexema}'"

    def _error(self, mensaje: str, sugerencia: str | None = None) -> ErrorSintactico:
        """Crea el error en la posición más útil para el usuario.

        Regla: si el token inesperado está en OTRA línea que el anterior (o es
        el EOF), el símbolo faltante debía ir justo al final del token anterior.
        Ejemplo: en ``int a = 5⏎print(a);`` el ``;`` falta en la línea 1, no en
        la 2. Si están en la misma línea, señalamos el token inesperado.
        """
        actual = self._actual()
        if self._pos > 0:
            previo = self._anterior()
            if actual.tipo is T.EOF or actual.linea != previo.linea:
                fin_previo = previo.columna + len(previo.lexema)
                return ErrorSintactico(mensaje, previo.linea, fin_previo, sugerencia)
        return ErrorSintactico(mensaje, actual.linea, actual.columna, sugerencia)

    def _entrar(self) -> None:
        """Registra un nivel más de anidamiento y aplica el límite de profundidad."""
        self._profundidad += 1
        if self._profundidad > PROFUNDIDAD_MAXIMA:
            raise self._error(
                f"Anidamiento demasiado profundo (más de {PROFUNDIDAD_MAXIMA} niveles de "
                "paréntesis, signos '-' o bloques).",
                "Divide la expresión usando variables intermedias.",
            )

    def _salir(self) -> None:
        self._profundidad -= 1

    # ------------------------------------------------------------- sentencias

    def _sentencia(self) -> Nodo:
        """sentencia → declaracion | asignacion | if | while | print

        Basta mirar UN token para decidir la regla (gramática LL(1)).
        """
        if self._ver(T.TIPO):
            return self._declaracion()
        if self._ver(T.IDENTIFICADOR):
            return self._asignacion()
        if self._ver(T.IF):
            return self._if()
        if self._ver(T.WHILE):
            return self._while()
        if self._ver(T.PRINT):
            return self._print()
        if self._ver(T.ELSE):
            raise self._error(
                "'else' sin un 'if' que lo preceda.",
                "Un 'else' debe ir justo después del bloque '}' de un if.",
            )
        raise self._error(
            "Se esperaba el inicio de una sentencia (declaración, asignación, if, while "
            f"o print) pero se encontró {self._describir()}.",
            "Revisa que la sentencia anterior esté completa y que no sobren símbolos.",
        )

    def _declaracion(self) -> Declaracion:
        """declaracion → TIPO nombre ( "=" expresion )? ";" """
        token_tipo = self._avanzar()
        if self._actual().tipo in PALABRAS_RESERVADAS_COMO_NOMBRE:
            token_nombre = self._avanzar()  # la fase semántica reportará el problema
        else:
            token_nombre = self._consumir(
                T.IDENTIFICADOR,
                f"un nombre de variable después de '{token_tipo.lexema}'",
                f"Ejemplo: {token_tipo.lexema} contador = 0;",
            )
        valor = None
        if self._ver(T.ASIGNAR):
            self._avanzar()
            valor = self._expresion()
        self._consumir(T.PUNTO_Y_COMA, "';' al final de la declaración", "Agrega ';'.")
        return Declaracion(
            token_tipo.valor,
            token_nombre.lexema,
            valor,
            linea=token_tipo.linea,
            columna=token_tipo.columna,
        )

    def _asignacion(self) -> Asignacion:
        """asignacion → IDENTIFICADOR "=" expresion ";" """
        token_nombre = self._avanzar()
        self._consumir(
            T.ASIGNAR,
            f"'=' después de '{token_nombre.lexema}'",
            "Una sentencia que empieza con un nombre es una asignación: nombre = valor;",
        )
        valor = self._expresion()
        self._consumir(T.PUNTO_Y_COMA, "';' al final de la asignación", "Agrega ';'.")
        return Asignacion(
            token_nombre.lexema, valor, linea=token_nombre.linea, columna=token_nombre.columna
        )

    def _condicion_entre_parentesis(self, palabra: str) -> Nodo:
        self._consumir(T.PAREN_IZQ, f"'(' después de '{palabra}'", f"Escribe {palabra} (x > 0)")
        condicion = self._expresion()
        self._consumir(
            T.PAREN_DER,
            f"')' para cerrar la condición del '{palabra}'",
            "La condición va completa entre paréntesis: (a > 0)",
        )
        return condicion

    def _if(self) -> If:
        """if → "if" "(" expresion ")" bloque ( "else" bloque )?"""
        token_if = self._avanzar()
        condicion = self._condicion_entre_parentesis("if")
        entonces = self._bloque()
        sino = None
        if self._ver(T.ELSE):
            self._avanzar()
            sino = self._bloque()
        return If(condicion, entonces, sino, linea=token_if.linea, columna=token_if.columna)

    def _while(self) -> While:
        """while → "while" "(" expresion ")" bloque"""
        token_while = self._avanzar()
        condicion = self._condicion_entre_parentesis("while")
        cuerpo = self._bloque()
        return While(condicion, cuerpo, linea=token_while.linea, columna=token_while.columna)

    def _print(self) -> Print:
        """print → "print" "(" expresion ")" ";" """
        token_print = self._avanzar()
        self._consumir(T.PAREN_IZQ, "'(' después de 'print'", "Escribe print(x);")
        expresion = self._expresion()
        self._consumir(T.PAREN_DER, "')' para cerrar el print", "Escribe print(x);")
        self._consumir(T.PUNTO_Y_COMA, "';' al final del print", "Agrega ';'.")
        return Print(expresion, linea=token_print.linea, columna=token_print.columna)

    def _bloque(self) -> list[Nodo]:
        """bloque → "{" sentencia* "}" """
        llave = self._consumir(
            T.LLAVE_IZQ, "'{' para abrir el bloque", "Mini exige llaves: { ... }"
        )
        self._entrar()
        sentencias = []
        while not self._ver(T.LLAVE_DER, T.EOF):
            sentencias.append(self._sentencia())
        self._consumir(
            T.LLAVE_DER,
            f"'}}' para cerrar el bloque abierto en la línea {llave.linea}",
            "Cada '{' necesita su '}'.",
        )
        self._salir()
        return sentencias

    # ------------------------------------------------------------ expresiones

    def _expresion(self) -> Nodo:
        """expresion → comparacion"""
        return self._comparacion()

    def _comparacion(self) -> Nodo:
        """comparacion → suma ( OP_RELACIONAL suma )?

        No asociativa: ``a < b < c`` se rechaza porque en Mini una comparación
        produce un bool y comparar un bool con un número no tiene sentido.
        """
        izquierda = self._suma()
        if self._actual().tipo in OPERADORES_RELACIONALES:
            operador = self._avanzar()
            derecha = self._suma()
            izquierda = self._binop(izquierda, operador, derecha)
            if self._actual().tipo in OPERADORES_RELACIONALES:
                raise self._error(
                    "Mini no permite encadenar comparaciones como 'a < b < c'.",
                    "Usa if anidados: if (a < b) { if (b < c) { ... } }",
                )
        return izquierda

    def _suma(self) -> Nodo:
        """suma → termino ( ("+"|"-") termino )*  (asociativa por la izquierda)"""
        izquierda = self._termino()
        while self._actual().tipo in OPERADORES_SUMA:
            operador = self._avanzar()
            izquierda = self._binop(izquierda, operador, self._termino())
        return izquierda

    def _termino(self) -> Nodo:
        """termino → factor ( ("*"|"/"|"%") factor )*  (asociativa por la izquierda)"""
        izquierda = self._factor()
        while self._actual().tipo in OPERADORES_PRODUCTO:
            operador = self._avanzar()
            izquierda = self._binop(izquierda, operador, self._factor())
        return izquierda

    def _factor(self) -> Nodo:
        """factor → NUMERO | BOOLEANO | IDENTIFICADOR | "(" expresion ")" | "-" factor"""
        token = self._actual()

        if token.tipo in (T.ENTERO, T.REAL, T.BOOLEANO):
            self._avanzar()
            return Numero(token.valor, linea=token.linea, columna=token.columna)

        if token.tipo is T.IDENTIFICADOR:
            self._avanzar()
            return Variable(token.valor, linea=token.linea, columna=token.columna)

        if token.tipo is T.PAREN_IZQ:
            self._avanzar()
            self._entrar()
            expresion = self._expresion()
            self._consumir(
                T.PAREN_DER,
                f"')' para cerrar el '(' de la línea {token.linea}, columna {token.columna}",
                "Cada '(' necesita su ')'.",
            )
            self._salir()
            return expresion  # los paréntesis NO generan nodo: ya están en la forma del árbol

        if token.tipo is T.MENOS:
            return self._menos_unario()

        raise self._error(
            f"Se esperaba un valor (número, variable o '(') pero se encontró {self._describir()}.",
            "Completa la expresión, por ejemplo: x = a + 1;",
        )

    def _menos_unario(self) -> Nodo:
        """``-x`` se traduce como ``0 - x`` (azúcar sintáctico) y ``-5`` como ``Numero(-5)``.

        Así las fases siguientes solo necesitan conocer operaciones binarias.
        """
        token = self._avanzar()
        self._entrar()
        operando = self._factor()
        self._salir()
        if isinstance(operando, Numero) and operando.tipo != "bool":
            return Numero(-operando.valor, linea=token.linea, columna=token.columna)
        cero = Numero(0, linea=token.linea, columna=token.columna)
        return BinOp(cero, "-", operando, linea=token.linea, columna=token.columna)

    @staticmethod
    def _binop(izquierda: Nodo, operador: Token, derecha: Nodo) -> BinOp:
        # La posición de un BinOp es la de su operador: ahí apuntan los errores.
        return BinOp(
            izquierda, operador.lexema, derecha, linea=operador.linea, columna=operador.columna
        )


def parsear(codigo: str) -> Programa:
    """Atajo: léxico + sintáctico en un paso."""
    return Parser(tokenizar(codigo)).parsear()
