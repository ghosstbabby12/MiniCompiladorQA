"""Pruebas del modo explicación y del CLI."""

import json
import subprocess
import sys

import pytest

from minicompilador.cli import main
from minicompilador.explicador import explicar
from minicompilador.reporte import compilar

ESPEC = "ejemplos/validos/programa_especificacion.mini"


def leer(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as archivo:
        return archivo.read()


# ---------------------------------------------------------------------------
# Explicador
# ---------------------------------------------------------------------------


def test_explicacion_responde_las_preguntas_de_la_sustentacion():
    # Arrange
    compilacion = compilar(leer(ESPEC))

    # Act
    texto = explicar(compilacion)

    # Assert: cada pregunta de la especificación tiene su sección.
    for fragmento in [
        "¿Hasta qué fase llegó la compilación?",
        "Resultado: ÉXITO.",
        "¿Qué operación hace cada línea y en qué orden?",
        "Línea 5: c = a + b * (a - 2) % 3;",
        "1) %t1 = a - 2",  # lo de los paréntesis va primero
        "DFS (búsqueda en profundidad) en POSTORDEN",
        "Variables temporales: 8",
        "%t2   se define como  %t2 = b * %t1",
        "Máximo de registros usados al mismo tiempo: 2.",
        "Instrucciones de procesador y memoria generadas",
        "LOAD R0, [a]",
        "R0 ← 1 si R0 > #10 (GT), si no 0",
        "Salida del programa: 3",
        "Advertencias (3)",
    ]:
        assert fragmento in texto, fragmento


def test_explicacion_de_un_error_senala_la_columna_con_un_caret():
    # Arrange
    compilacion = compilar("int a = 5;\nint b = a @ 2;")

    # Act
    texto = explicar(compilacion)

    # Assert: '@' está en la columna 11 → el '^' va tras 10 espacios.
    assert "      2 | int b = a @ 2;" in texto
    assert "        | " + " " * 10 + "^" in texto
    assert "✘ ERROR (aquí se detuvo)" in texto
    assert "Por qué:  El analizador léxico" in texto


@pytest.mark.parametrize(
    ("codigo", "fragmento"),
    [
        ("int a = ;", "Por qué:  Todas las palabras son válidas"),
        ("x = 1;", "Por qué:  La frase es gramaticalmente correcta"),
        ("int x = 1 / 0;", "Por qué:  El programa compiló sin problemas"),
    ],
)
def test_explicacion_del_por_que_segun_la_fase(codigo, fragmento):
    # Arrange
    compilacion = compilar(codigo)

    # Act
    texto = explicar(compilacion)

    # Assert
    assert fragmento in texto


def test_explicacion_con_fase_omitida_spill_y_optimizacion():
    # Arrange
    compilacion = compilar(leer("ejemplos/validos/spill_registros.mini"), hasta_fase=5)

    # Act
    texto = explicar(compilacion)

    # Assert
    assert "– omitida (--fase)" in texto
    assert "Spills (temporales enviadas a memoria): 1." in texto
    assert "[SPILL]" in texto
    assert "Ejecución en la CPU simulada" not in texto


def test_explicacion_de_programa_vacio():
    # Arrange
    compilacion = compilar("")

    # Act
    texto = explicar(compilacion)

    # Assert
    assert "(no se declararon variables)" in texto
    assert "(el programa no genera operaciones)" in texto
    assert "Salida del programa: (nada)" in texto


def test_explicacion_describe_todas_las_instrucciones_y_el_plegado():
    # Arrange
    compilacion = compilar("float y = 2 * 3;\nprint(y / 4);")

    # Act
    texto = explicar(compilacion)

    # Assert
    assert "Plegado de constantes" in texto
    assert "Línea 1: 2 * 3 → 6" in texto
    assert "DIV R0, R0, #4" in texto
    assert "imprime R0" in texto


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_por_defecto_imprime_la_salida_del_programa(capsys):
    # Arrange
    argumentos = [ESPEC]

    # Act
    codigo_salida = main(argumentos)
    capturado = capsys.readouterr()

    # Assert
    assert codigo_salida == 0
    assert capturado.out == "3\n"
    assert "✔ Fase alcanzada: Simulación" in capturado.err
    assert "⚠" in capturado.err


def test_cli_json_imprime_el_reporte(capsys):
    # Arrange
    argumentos = [ESPEC, "--json", "--fase", "4"]

    # Act
    codigo_salida = main(argumentos)
    reporte = json.loads(capsys.readouterr().out)

    # Assert
    assert codigo_salida == 0
    assert reporte["fase_alcanzada"] == "intermedio"
    assert reporte["metricas"] is None


def test_cli_explicar(capsys):
    # Arrange
    argumentos = [ESPEC, "--explicar"]

    # Act
    main(argumentos)

    # Assert
    assert "modo explicación" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("archivo", "codigo_esperado"),
    [
        ("ejemplos/errores/lexico_modulo_como_identificador.mini", 1),
        ("ejemplos/errores/semantico_redeclaracion.mini", 1),
        ("no_existe.mini", 2),
    ],
)
def test_cli_codigos_de_salida(archivo, codigo_esperado, capsys):
    # Arrange
    argumentos = [archivo]

    # Act
    codigo_salida = main(argumentos)

    # Assert
    assert codigo_salida == codigo_esperado
    assert capsys.readouterr().err


def test_cli_limite_de_ciclos(capsys):
    # Arrange
    argumentos = ["ejemplos/errores/ejecucion_bucle_infinito.mini", "--limite-ciclos", "50"]

    # Act
    codigo_salida = main(argumentos)

    # Assert
    assert codigo_salida == 1
    assert "límite de 50 ciclos" in capsys.readouterr().err


@pytest.mark.parametrize("fase", ["0", "7", "x"])
def test_cli_rechaza_fase_invalida(fase, capsys):
    # Arrange: off points del rango 1..6 y un valor no numérico.
    # Act / Assert: argparse termina con código 2 (error de uso).
    with pytest.raises(SystemExit) as salida:
        main([ESPEC, "--fase", fase])
    assert salida.value.code == 2


def test_python_m_minicompilador_funciona_de_punta_a_punta():
    # Arrange: prueba de integración real del punto de entrada del paquete.
    comando = [sys.executable, "-m", "minicompilador", ESPEC]

    # Act
    proceso = subprocess.run(comando, capture_output=True, text=True, check=False)

    # Assert
    assert proceso.returncode == 0
    assert proceso.stdout == "3\n"


def test_explicacion_de_error_sin_posicion():
    # Arrange: 'print(1);' cuesta 2 ciclos; con límite 1 se pasa en el HALT,
    # que no corresponde a ninguna línea del código Mini.
    compilacion = compilar("print(1);", limite_ciclos=1)

    # Act
    texto = explicar(compilacion)

    # Assert
    assert "sin posición" in texto
    assert " | " not in texto.split("Análisis del error")[1]  # no hay línea que mostrar


def test_descripcion_de_jnz():
    # Arrange: JNZ existe en la ISA aunque el traductor use JZ.
    from minicompilador.cpu import InstruccionCPU, RefEtiqueta, Registro
    from minicompilador.explicador import _describir_cpu

    instruccion = InstruccionCPU("JNZ", (Registro(1), RefEtiqueta("L1")))

    # Act
    texto = _describir_cpu(instruccion)

    # Assert
    assert texto == "si R1 no es 0 salta a L1"


def test_python_m_en_el_mismo_proceso(monkeypatch, capsys):
    # Arrange: runpy ejecuta __main__.py dentro del proceso para medir su cobertura.
    import runpy

    monkeypatch.setattr(sys, "argv", ["minicompilador", ESPEC])

    # Act
    with pytest.raises(SystemExit) as salida:
        runpy.run_module("minicompilador", run_name="__main__")

    # Assert
    assert salida.value.code == 0
    assert capsys.readouterr().out == "3\n"
