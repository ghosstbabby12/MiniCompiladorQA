"""Pruebas de la asignación de registros (linear scan + spill)."""

import pytest

from minicompilador.intermedio import generar_intermedio
from minicompilador.parser import parsear
from minicompilador.registros import (
    DIRECCION_BASE_SPILL,
    NUM_REGISTROS,
    Intervalo,
    asignar_registros,
    calcular_intervalos,
)

# Expresiones cuyo número de temporales vivas a la vez se calculó a mano:
#   CUATRO_VIVAS: %t1=a*b %t2=c*d %t3=e*f %t4=%t2+%t3 → en %t4 viven t1,t2,t3,t4
#   CINCO_VIVAS:  agrega g*h → en %t5 viven t1..t5 (una más que registros)
CUATRO_VIVAS = "x = a * b + (c * d + e * f);"
CINCO_VIVAS = "x = a * b + (c * d + (e * f + g * h));"


def registros_de(codigo: str):
    return asignar_registros(generar_intermedio(parsear(codigo)).instrucciones)


def test_intervalos_de_vida():
    # Arrange
    instrucciones = generar_intermedio(parsear("x = a + b * c;")).instrucciones
    # 0: %t1 = b * c   1: %t2 = a + %t1   2: x = %t2

    # Act
    intervalos = calcular_intervalos(instrucciones)

    # Assert
    assert intervalos == [Intervalo("%t1", 0, 1), Intervalo("%t2", 1, 2)]


def test_temporal_que_nadie_lee_vive_solo_en_su_definicion():
    # Arrange: una condición de if siempre se lee; aquí forzamos un caso sin lectura
    # usando el intervalo calculado sobre una lista de una sola operación.
    instrucciones = generar_intermedio(parsear("x = a + b;")).instrucciones[:1]

    # Act
    intervalos = calcular_intervalos(instrucciones)

    # Assert
    assert intervalos == [Intervalo("%t1", 0, 0)]


def test_programa_sin_temporales():
    # Arrange: partición "sin operaciones".
    codigo = "int total = 5;\nprint(total);"

    # Act
    resultado = registros_de(codigo)

    # Assert
    assert resultado.asignacion == {}
    assert resultado.max_registros_simultaneos == 0
    assert resultado.max_temporales_vivas == 0
    assert resultado.spills == 0


def test_asigna_el_registro_libre_de_numero_mas_bajo():
    # Arrange
    codigo = "x = a + b * c;"

    # Act
    resultado = registros_de(codigo)

    # Assert: %t1 sigue viva cuando nace %t2, así que no comparten registro.
    assert resultado.asignacion == {"%t1": "R0", "%t2": "R1"}
    assert resultado.max_registros_simultaneos == 2


def test_registro_se_reutiliza_cuando_la_temporal_muere():
    # Arrange: dos sentencias independientes; %t1 muere antes de que nazca %t2.
    codigo = "x = a + b;\ny = c + d;"

    # Act
    resultado = registros_de(codigo)

    # Assert
    assert resultado.asignacion == {"%t1": "R0", "%t2": "R0"}
    assert resultado.max_registros_simultaneos == 1


@pytest.mark.parametrize(
    ("codigo", "vivas", "registros_usados", "spills"),
    [
        (CUATRO_VIVAS, 4, 4, 0),  # ON point: usa exactamente los 4 registros
        (CINCO_VIVAS, 5, 4, 1),  # OFF point: la 5.ª temporal va a memoria
    ],
)
def test_valor_limite_cuatro_vs_cinco_registros(codigo, vivas, registros_usados, spills):
    # Arrange
    assert NUM_REGISTROS == 4

    # Act
    resultado = registros_de(codigo)

    # Assert
    assert resultado.max_temporales_vivas == vivas
    assert resultado.max_registros_simultaneos == registros_usados
    assert resultado.spills == spills


def test_spill_usa_la_zona_de_memoria_y_genera_advertencia():
    # Arrange
    codigo = CINCO_VIVAS

    # Act
    resultado = registros_de(codigo)

    # Assert
    assert resultado.direcciones_spill == {"%t5": DIRECCION_BASE_SPILL}
    assert resultado.asignacion["%t5"] == "MEM[2000]"
    assert resultado.registro_de("%t5") is None
    assert resultado.registro_de("%t1") == "R0"
    assert [a.codigo for a in resultado.advertencias] == ["SPILL"]
    assert resultado.advertencias[0].fase == "registros"


def test_nunca_se_usan_mas_de_cuatro_registros():
    # Arrange: expresión con mucha presión (7 productos anidados).
    terminos = " + (".join(f"v{i} * w{i}" for i in range(7)) + ")" * 6
    codigo = f"x = {terminos};"

    # Act
    resultado = registros_de(codigo)

    # Assert
    usados = {r for r in resultado.asignacion.values() if r.startswith("R")}
    assert usados <= {"R0", "R1", "R2", "R3"}
    assert resultado.max_registros_simultaneos == NUM_REGISTROS
    assert resultado.spills == resultado.max_temporales_vivas - NUM_REGISTROS + 2
    # las direcciones de spill avanzan de a 4 bytes
    assert list(resultado.direcciones_spill.values()) == list(
        range(2000, 2000 + 4 * resultado.spills, 4)
    )


@pytest.mark.parametrize(
    ("posicion", "vivo"),
    [(1, False), (2, True), (5, True), (6, False)],  # bordes del intervalo [2, 5]
)
def test_intervalo_vivo_en_incluye_ambos_extremos(posicion, vivo):
    # Arrange
    intervalo = Intervalo("%t1", 2, 5)

    # Act / Assert
    assert intervalo.vivo_en(posicion) is vivo


# ---------------------------------------------------------------------------
# Optimización de _max_vivas: la versión O(n²) original queda como ORÁCULO
# ---------------------------------------------------------------------------


def _max_vivas_ingenuo(intervalos):
    """Definición directa (lenta pero obviamente correcta)."""
    return max(
        (sum(otro.vivo_en(i.inicio) for otro in intervalos) for i in intervalos),
        default=0,
    )


@pytest.mark.parametrize("semilla", range(25))
def test_max_vivas_por_barrido_coincide_con_el_oraculo(semilla):
    # Arrange: intervalos aleatorios (reproducibles por la semilla), con
    # casos de borde: inicio == fin y fines que coinciden con inicios.
    import random

    from minicompilador.registros import Intervalo, _max_vivas

    azar = random.Random(semilla)
    intervalos = []
    for numero in range(azar.randint(0, 40)):
        inicio = azar.randint(0, 30)
        intervalos.append(Intervalo(f"%t{numero + 1}", inicio, inicio + azar.randint(0, 6)))

    # Act
    resultado = _max_vivas(intervalos)

    # Assert
    assert resultado == _max_vivas_ingenuo(intervalos)


def test_max_vivas_cuenta_como_vivos_los_que_mueren_donde_otro_nace():
    # Arrange: valor límite del intervalo cerrado: %t1 muere en 3 y %t2 nace en 3.
    from minicompilador.registros import Intervalo, _max_vivas

    intervalos = [Intervalo("%t1", 0, 3), Intervalo("%t2", 3, 5)]

    # Act / Assert: en la posición 3 ambos están vivos.
    assert _max_vivas(intervalos) == 2
