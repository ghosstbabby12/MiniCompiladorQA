"""Pruebas del traductor a la ISA y del simulador de CPU + memoria."""

import pytest

from minicompilador.cpu import (
    CPU,
    ETIQUETA,
    Inmediato,
    InstruccionCPU,
    Memoria,
    RefEtiqueta,
    Registro,
)
from minicompilador.errores import ErrorEjecucion
from minicompilador.reporte import compilar


def ejecutar(codigo: str, **opciones):
    """Helper: compila hasta la simulación y devuelve la Compilacion."""
    return compilar(codigo, **opciones)


def cpu_de(codigo: str) -> list[str]:
    return [str(i) for i in compilar(codigo, hasta_fase=5).codigo_cpu]


# ---------------------------------------------------------------------------
# Traducción TAC → ISA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("int x = 5;", ["MOV [x], #5", "HALT"]),
        ("int a = 1;\nint x = a;", ["MOV [a], #1", "MOV [x], [a]", "HALT"]),
        # Primer operando en memoria → LOAD al registro destino y se opera ahí.
        (
            "int b = 1;\nint x = b * 2;",
            ["MOV [b], #1", "LOAD R0, [b]", "MUL R0, R0, #2", "STORE [x], R0", "HALT"],
        ),
        # Primer operando inmediato → MOV (no es un acceso a memoria).
        (
            "int b = 1;\nint x = 2 - b;",
            ["MOV [b], #1", "MOV R0, #2", "SUB R0, R0, [b]", "STORE [x], R0", "HALT"],
        ),
        (
            "int a = 1;\nbool f = a < 3;",
            ["MOV [a], #1", "LOAD R0, [a]", "CMP R0, R0, #3, LT", "STORE [f], R0", "HALT"],
        ),
        ("print(true);", ["PRINT #true", "HALT"]),
    ],
)
def test_traduccion_a_instrucciones_de_cpu(codigo, esperado):
    # Arrange (en parámetros)
    # Act
    resultado = cpu_de(codigo)

    # Assert
    assert resultado == esperado


def test_traduccion_de_saltos_y_etiquetas():
    # Arrange
    codigo = "int a = 1;\nwhile (a > 0) { a = a - 1; }"

    # Act
    resultado = cpu_de(codigo)

    # Assert
    assert resultado == [
        "MOV [a], #1",
        "L1:",
        "LOAD R0, [a]",
        "CMP R0, R0, #0, GT",
        "JZ R0, L2",
        "LOAD R0, [a]",
        "SUB R0, R0, #1",
        "STORE [a], R0",
        "JMP L1",
        "L2:",
        "HALT",
    ]


def test_temporal_con_spill_opera_directo_en_memoria():
    # Arrange
    codigo = (
        "int a=1; int b=2; int c=3; int d=4; int e=5; int f=6; int g=7; int h=8;\n"
        "int x = a * b + (c * d + (e * f + g * h));"
    )

    # Act
    resultado = cpu_de(codigo)

    # Assert: %t5 no tiene registro → su resultado se escribe en [%t5].
    assert "ADD [%t5], R2, R3" in resultado
    assert "ADD R2, R1, [%t5]" in resultado


# ---------------------------------------------------------------------------
# Simulación: resultados, memoria tipada y métricas
# ---------------------------------------------------------------------------


def test_programa_de_la_especificacion_se_ejecuta_correctamente():
    # Arrange
    with open("ejemplos/validos/programa_especificacion.mini", encoding="utf-8") as archivo:
        codigo = archivo.read()

    # Act
    resultado = ejecutar(codigo).cpu

    # Assert: c = 5 + (2.5 * 3) % 3 = 6.5 → int 6; 6 > 10 es falso → c = 3.
    assert resultado.salida == ["3"]
    assert resultado.memoria_final == {"a": 0, "b": 2.5, "c": 3}


@pytest.mark.parametrize(
    ("codigo", "variable", "valor"),
    [
        ("int x = 6.9;", "x", 6),  # memoria tipada: trunca float → int
        ("int x = -6.9;", "x", -6),  # hacia cero, no hacia -∞
        ("float y = 5;", "y", 5.0),  # promueve int → float
        ("float y = 7 / 2;", "y", 3.0),  # división entera ANTES de guardar (como C)
        ("float y = 7.0 / 2;", "y", 3.5),
        ("bool f = 1 < 2;", "f", True),
        ("int x;", "x", 0),  # declarada sin valor: la memoria arranca en 0
        ("float y;", "y", 0.0),
        ("bool f;", "f", False),
    ],
)
def test_memoria_tipada(codigo, variable, valor):
    # Arrange (en parámetros)
    # Act
    memoria = ejecutar(codigo).cpu.memoria_final

    # Assert
    assert memoria[variable] == valor
    assert type(memoria[variable]) is type(valor)


def test_spill_no_cambia_el_resultado():
    # Arrange: con y sin spill el valor debe ser el mismo (1*2 + (3*4 + (5*6 + 7*8))).
    codigo = (
        "int a=1; int b=2; int c=3; int d=4; int e=5; int f=6; int g=7; int h=8;\n"
        "print(a * b + (c * d + (e * f + g * h)));"
    )

    # Act
    compilacion = ejecutar(codigo)

    # Assert
    assert compilacion.registros.spills == 1
    assert compilacion.cpu.salida == ["100"]


@pytest.mark.parametrize(
    ("codigo", "salida"),
    [
        ("print(1 < 2);", ["true"]),
        ("print(2.5);", ["2.5"]),
        ("int i = 3;\nwhile (i > 0) { print(i); i = i - 1; }", ["3", "2", "1"]),
        ("int n = 0;\nif (n == 0) { print(1); } else { print(2); }", ["1"]),
        ("int n = 5;\nif (n == 0) { print(1); } else { print(2); }", ["2"]),
        ("int n = 0;\nwhile (n > 0) { print(n); }", []),  # cero vueltas (valor límite)
    ],
)
def test_salida_del_programa(codigo, salida):
    # Arrange (en parámetros)
    # Act
    resultado = ejecutar(codigo).cpu.salida

    # Assert
    assert resultado == salida


def test_metricas_exactas_de_un_programa_pequeno():
    # Arrange
    codigo = "int x = 5;\nprint(x);"
    # MOV [x], #5   → 1 escritura → 1 + 2 = 3 ciclos
    # PRINT [x]     → 1 lectura   → 1 + 2 = 3 ciclos
    # HALT          →             → 1 ciclo

    # Act
    metricas = ejecutar(codigo).cpu.metricas()

    # Assert
    assert metricas == {
        "ciclos": 7,
        "lecturas_memoria": 1,
        "escrituras_memoria": 1,
        "instrucciones_ejecutadas": 3,
    }


# ---------------------------------------------------------------------------
# Errores de ejecución
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "patron", "linea"),
    [
        ("int x = 5 / 0;", r"División por cero en la línea 1: se intentó calcular 5 / 0", 1),
        ("int d = 0;\nint x = 7 % d;", "Módulo por cero en la línea 2", 2),
        ("float d = 0.0;\nfloat x = 1.5 / d;", "División por cero", 2),
    ],
)
def test_division_por_cero_es_error_de_ejecucion(codigo, patron, linea):
    # Arrange (en parámetros): valor límite "divisor = 0" (entero y real).
    # Act
    compilacion = ejecutar(codigo)

    # Assert
    assert isinstance(compilacion.error, ErrorEjecucion)
    assert compilacion.error.linea == linea
    with pytest.raises(ErrorEjecucion, match=patron):
        raise compilacion.error


@pytest.mark.parametrize(
    ("codigo", "patron", "linea"),
    [
        ("int x = 2147483647 + 1;", "2147483648 no cabe en un int de 32 bits", 1),
        ("int x = 0;\nx = -2147483647 - 2;", "-2147483649 no cabe", 2),  # mínimo - 1
        ("float f = 3000000000.0;\nint x = f;", "3000000000 no cabe", 2),  # float→int
        ("float f = 1" + "0" * 308 + ".0;\nf = f * 10.0;", "infinito", 2),
    ],
)
def test_desbordamiento_es_error_de_ejecucion(codigo, patron, linea):
    # Arrange (en parámetros): off points del rango de int y de float.
    # Act
    compilacion = ejecutar(codigo)

    # Assert
    assert isinstance(compilacion.error, ErrorEjecucion)
    assert compilacion.error.linea == linea
    with pytest.raises(ErrorEjecucion, match=patron):
        raise compilacion.error


def test_salida_parcial_se_conserva_tras_un_error_de_ejecucion():
    # Arrange
    codigo = "print(1);\nint x = 1 / 0;"

    # Act
    compilacion = ejecutar(codigo)

    # Assert
    assert compilacion.cpu.salida == ["1"]
    assert compilacion.fases_completadas[-1] == "registros"


@pytest.mark.parametrize(
    ("limite", "falla"),
    [
        (2, False),  # ON point: llegar EXACTAMENTE al límite está permitido
        (1, True),  # OFF point: un ciclo menos ya es error
    ],
)
def test_valor_limite_de_ciclos(limite, falla):
    # Arrange: 'print(1);' cuesta exactamente 2 ciclos (PRINT #1 + HALT).
    codigo = "print(1);"

    # Act
    compilacion = ejecutar(codigo, limite_ciclos=limite)

    # Assert
    assert (compilacion.error is not None) is falla
    if not falla:
        assert compilacion.cpu.ciclos == limite


def test_bucle_infinito_se_detecta_por_limite_de_ciclos():
    # Arrange
    codigo = "int vueltas = 0;\nwhile (true) { vueltas = vueltas + 1; }"

    # Act
    compilacion = ejecutar(codigo, limite_ciclos=1_000)

    # Assert
    assert isinstance(compilacion.error, ErrorEjecucion)
    assert "bucle infinito" in compilacion.error.mensaje
    assert compilacion.cpu.ciclos > 1_000
    assert compilacion.cpu.memoria_final["vueltas"] > 0


# ---------------------------------------------------------------------------
# ISA directa (instrucciones que el traductor no genera) y validaciones
# ---------------------------------------------------------------------------


def test_jnz_y_halt_con_programa_escrito_a_mano():
    # Arrange: cuenta regresiva 2, 1 usando JNZ; el HALT corta antes del PRINT final.
    r0 = Registro(0)
    programa = [
        InstruccionCPU("MOV", (r0, Inmediato(2))),
        InstruccionCPU(ETIQUETA, (RefEtiqueta("BUCLE"),)),
        InstruccionCPU("PRINT", (r0,)),
        InstruccionCPU("SUB", (r0, r0, Inmediato(1))),
        InstruccionCPU("JNZ", (r0, RefEtiqueta("BUCLE"))),
        InstruccionCPU("STORE", (Memoria("x"), r0)),
        InstruccionCPU("HALT"),
        InstruccionCPU("PRINT", (Inmediato(99),)),
    ]

    # Act
    resultado = CPU().ejecutar(programa, {"x": 1000}, {"x": "int"})

    # Assert
    assert resultado.salida == ["2", "1"]
    assert resultado.memoria_final == {"x": 0}
    assert resultado.registros == [0, 0, 0, 0]


def test_programa_sin_halt_termina_al_final():
    # Arrange
    programa = [InstruccionCPU("PRINT", (Inmediato(7),))]

    # Act
    resultado = CPU().ejecutar(programa, {}, {})

    # Assert
    assert resultado.salida == ["7"]
    assert resultado.instrucciones_ejecutadas == 1


@pytest.mark.parametrize(
    ("programa", "patron"),
    [
        ([InstruccionCPU("NOP")], "Opcode desconocido"),
        ([InstruccionCPU("JMP", (RefEtiqueta("NADA"),))], "Etiqueta no definida"),
        ([InstruccionCPU("PRINT", (Registro(4),))], "solo tiene R0-R3"),  # off point
        ([InstruccionCPU("PRINT", (Memoria("y"),))], "Sin dirección de memoria"),
        ([InstruccionCPU("MOV", (Inmediato(1), Inmediato(2)))], "No se puede escribir"),
        (
            [
                InstruccionCPU("PRINT", (RefEtiqueta("L1"),)),
                InstruccionCPU(ETIQUETA, (RefEtiqueta("L1"),)),
            ],
            "no legible",
        ),  # fmt: skip # noqa: E501
    ],
)
def test_programas_mal_formados_se_rechazan(programa, patron):
    # Arrange (en parámetros): errores del traductor, no del usuario → ValueError.
    # Act / Assert
    with pytest.raises(ValueError, match=patron):
        CPU().ejecutar(programa, {}, {})


def test_registro_r3_es_valido():
    # Arrange: R3 es el ON point del rango de registros (R4 es el off point).
    programa = [InstruccionCPU("MOV", (Registro(3), Inmediato(1)))]

    # Act
    resultado = CPU().ejecutar(programa, {}, {})

    # Assert
    assert resultado.registros[3] == 1


def test_traductor_rechaza_instrucciones_tac_desconocidas():
    # Arrange: la clase base Instruccion no tiene traducción a la ISA.
    from minicompilador.cpu import traducir_a_cpu
    from minicompilador.intermedio import Instruccion
    from minicompilador.registros import asignar_registros

    instrucciones = [Instruccion()]

    # Act / Assert
    with pytest.raises(ValueError, match="sin traducción"):
        traducir_a_cpu(instrucciones, asignar_registros(instrucciones))
