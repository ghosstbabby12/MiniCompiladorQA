"""Pruebas de CARGA de la API con Locust.

Tres tareas con PESO (de cada 10 solicitudes, en promedio):
    6 → programa corto   (el caso típico: el ejemplo de la especificación)
    3 → programa largo   (~200 sentencias + bucle: estresa todas las fases)
    1 → programa con error (debe responder 422 rápido: falla en el semántico)

Ejecución sin interfaz (la usada para docs/RENDIMIENTO.md):
    locust -f tests/carga/locustfile.py --host http://localhost:8000 \\
           --headless -u 20 -r 5 -t 30s --csv resultados/carga

Quality gate de rendimiento (al terminar, exit code 1 si no se cumple):
    * tasa de fallos > 1 %                → falla
    * p95 global > P95_MAXIMO_MS (500 ms) → falla
Los umbrales se cambian con variables de entorno del mismo nombre.
"""

import os
from pathlib import Path

from locust import HttpUser, between, events, task

RAIZ = Path(__file__).resolve().parents[2]

P95_MAXIMO_MS = float(os.environ.get("P95_MAXIMO_MS", "500"))
TASA_FALLOS_MAXIMA = float(os.environ.get("TASA_FALLOS_MAXIMA", "0.01"))

PROGRAMA_CORTO = (RAIZ / "ejemplos" / "validos" / "programa_especificacion.mini").read_text(
    encoding="utf-8"
)


def generar_programa_largo(variables: int = 60) -> str:
    """Programa grande pero válido: declaraciones, expresiones, if y un while."""
    lineas = [f"int valor_{i} = {i} * 2 + 1;" for i in range(variables)]
    lineas += [
        f"valor_{i} = (valor_{i - 1} + valor_{i}) % 97 * 3 - {i};" for i in range(1, variables)
    ]
    lineas += [
        "int contador = 0;",
        "int suma = 0;",
        "while (contador < 50) {",
        "    suma = suma + contador % 7;",
        "    if (suma > 100) { suma = suma - 100; } else { suma = suma + 1; }",
        "    contador = contador + 1;",
        "}",
        "print(suma);",
    ]
    return "\n".join(lineas)


PROGRAMA_LARGO = generar_programa_largo()
PROGRAMA_CON_ERROR = "int total = 5;\ntotal = total + desconocida;\nprint(total);"


class UsuarioCompilador(HttpUser):
    # Tiempo de "pensar" entre solicitudes: simula personas, no un bucle cerrado.
    wait_time = between(0.1, 0.5)

    def _compilar(self, nombre: str, codigo: str, estado_esperado: int) -> None:
        with self.client.post(
            "/compilar", json={"codigo": codigo}, name=nombre, catch_response=True
        ) as respuesta:
            # Un 422 ESPERADO es éxito; un 200 donde se esperaba 422 es un fallo.
            if respuesta.status_code != estado_esperado:
                respuesta.failure(f"HTTP {respuesta.status_code}, se esperaba {estado_esperado}")
            elif "fase_alcanzada" not in respuesta.json():
                respuesta.failure("el cuerpo no es un reporte")
            else:
                respuesta.success()

    @task(6)
    def programa_corto(self) -> None:
        self._compilar("POST /compilar [corto]", PROGRAMA_CORTO, 200)

    @task(3)
    def programa_largo(self) -> None:
        self._compilar("POST /compilar [largo]", PROGRAMA_LARGO, 200)

    @task(1)
    def programa_con_error(self) -> None:
        self._compilar("POST /compilar [error]", PROGRAMA_CON_ERROR, 422)


@events.quitting.add_listener
def quality_gate(environment, **_kwargs) -> None:
    """Pone exit code 1 si el rendimiento no cumple los umbrales (útil en CI)."""
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) or 0
    print(
        f"\n[gate] solicitudes={total.num_requests} RPS={total.total_rps:.1f} "
        f"p50={total.get_response_time_percentile(0.5)} ms p95={p95} ms "
        f"fallos={total.fail_ratio:.2%}"
    )
    if total.fail_ratio > TASA_FALLOS_MAXIMA:
        print(f"[gate] ✘ tasa de fallos > {TASA_FALLOS_MAXIMA:.0%}")
        environment.process_exit_code = 1
    elif p95 > P95_MAXIMO_MS:
        print(f"[gate] ✘ p95 {p95} ms > {P95_MAXIMO_MS:.0f} ms")
        environment.process_exit_code = 1
    else:
        print("[gate] ✔ rendimiento dentro de los umbrales")
