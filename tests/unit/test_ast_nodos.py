"""Pruebas de los nodos del AST: impresión, serialización y patrón Visitor."""

import pytest

from minicompilador.ast_nodos import (
    BinOp,
    Numero,
    Variable,
    Visitante,
    imprimir_arbol,
    nodo_a_dict,
)
from minicompilador.parser import parsear


def test_imprimir_arbol_de_una_asignacion_muestra_la_precedencia():
    # Arrange
    programa = parsear("c = a + b * 2;")

    # Act
    texto = imprimir_arbol(programa)

    # Assert: el '*' queda más profundo que el '+' (se evalúa primero).
    assert texto == (
        "Programa\n"
        "└── Asignacion c =\n"
        "    └── BinOp '+'\n"
        "        ├── Variable a\n"
        "        └── BinOp '*'\n"
        "            ├── Variable b\n"
        "            └── Numero 2 (int)"
    )


def test_imprimir_arbol_con_bloques_rotulos_y_bloque_vacio():
    # Arrange
    programa = parsear("int x = 1;\nif (x > 0) { print(x); } else { }")

    # Act
    texto = imprimir_arbol(programa)

    # Assert
    assert texto == (
        "Programa\n"
        "├── Declaracion int x\n"
        "│   └── valor: Numero 1 (int)\n"
        "└── If\n"
        "    ├── condicion: BinOp '>'\n"
        "    │   ├── Variable x\n"
        "    │   └── Numero 0 (int)\n"
        "    ├── entonces\n"
        "    │   └── Print\n"
        "    │       └── Variable x\n"
        "    └── sino (vacío)"
    )


def test_imprimir_arbol_de_while_con_if_sin_else():
    # Arrange: un If sin else NO debe imprimir la rama "sino".
    programa = parsear("while (a) { if (a) { } }")

    # Act
    texto = imprimir_arbol(programa)

    # Assert
    assert texto == (
        "Programa\n"
        "└── While\n"
        "    ├── condicion: Variable a\n"
        "    └── cuerpo\n"
        "        └── If\n"
        "            ├── condicion: Variable a\n"
        "            └── entonces (vacío)"
    )


@pytest.mark.parametrize(
    ("valor", "tipo", "etiqueta"),
    [
        (5, "int", "Numero 5 (int)"),
        (2.5, "float", "Numero 2.5 (float)"),
        # bool es subclase de int en Python: hay que distinguirlo primero.
        (True, "bool", "Numero true (bool)"),
        (False, "bool", "Numero false (bool)"),
    ],
)
def test_numero_deduce_su_tipo_desde_el_valor(valor, tipo, etiqueta):
    # Arrange
    nodo = Numero(valor)

    # Act / Assert
    assert nodo.tipo == tipo
    assert nodo.etiqueta() == etiqueta


def test_igualdad_ignora_posiciones():
    # Arrange
    nodo_a = Variable("x", linea=1, columna=1)
    nodo_b = Variable("x", linea=9, columna=9)

    # Act
    son_iguales = nodo_a == nodo_b

    # Assert
    assert son_iguales


def test_nodo_a_dict_serializa_el_arbol_completo():
    # Arrange
    programa = parsear("x = a * 2;")

    # Act
    datos = nodo_a_dict(programa)

    # Assert
    assert datos == {
        "nodo": "Programa",
        "linea": 1,
        "columna": 1,
        "sentencias": [
            {
                "nodo": "Asignacion",
                "linea": 1,
                "columna": 1,
                "nombre": "x",
                "valor": {
                    "nodo": "BinOp",
                    "linea": 1,
                    "columna": 7,
                    "izquierda": {"nodo": "Variable", "linea": 1, "columna": 5, "nombre": "a"},
                    "op": "*",
                    "derecha": {"nodo": "Numero", "linea": 1, "columna": 9, "valor": 2},
                },
            }
        ],
    }


class ContadorDeVariables(Visitante):
    """Visitante mínimo de prueba: cuenta usos de variables en una expresión."""

    def visitar_binop(self, nodo):
        return self.visitar(nodo.izquierda) + self.visitar(nodo.derecha)

    def visitar_variable(self, nodo):
        return 1

    def visitar_numero(self, nodo):
        return 0


def test_visitor_despacha_al_metodo_de_cada_tipo_de_nodo():
    # Arrange
    expresion = BinOp(Variable("a"), "+", BinOp(Numero(2), "*", Variable("b")))

    # Act
    cantidad = ContadorDeVariables().visitar(expresion)

    # Assert
    assert cantidad == 2


def test_visitor_sin_metodo_para_un_nodo_falla_con_mensaje_claro():
    # Arrange
    programa = parsear("print(1);")

    # Act / Assert
    with pytest.raises(NotImplementedError, match="no sabe visitar nodos 'Programa'"):
        ContadorDeVariables().visitar(programa)
