"""Configuración de las pruebas de CONTRATO (cliente HTTP externo).

Estas pruebas NO importan ``minicompilador``: tratan la API como una caja negra
que se consume por HTTP, igual que haría otro equipo. Por eso corren en un
contenedor distinto (``test-runner``) del que sirve la API (``api``).

Variable de entorno:
    API_URL  URL base de la API (en docker compose: http://api:8000).
             Si NO está definida, las pruebas se OMITEN (skip) para que un
             ``pytest`` local sin servidor no falle. Si SÍ está definida pero la
             API no responde, es un FALLO: en el pipeline eso es un problema real.
"""

import json
import os
import time
from pathlib import Path

import pytest
import requests

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA_DEL_CONSUMIDOR = RAIZ / "src" / "minicompilador" / "esquemas" / "reporte.schema.json"


ESPERA_MAXIMA_SEGUNDOS = 30


@pytest.fixture(scope="session")
def url_api() -> str:
    url = os.environ.get("API_URL")
    if not url:
        pytest.skip("API_URL no definida: las pruebas de contrato necesitan la API corriendo")
    url = url.rstrip("/")

    # Reintentos: el contenedor puede tardar unos segundos en aceptar conexiones.
    limite = time.monotonic() + ESPERA_MAXIMA_SEGUNDOS
    while True:
        try:
            if requests.get(f"{url}/salud", timeout=2).status_code == 200:
                return url
        except requests.ConnectionError:
            pass
        if time.monotonic() > limite:
            pytest.fail(f"La API en {url} no respondió en {ESPERA_MAXIMA_SEGUNDOS} s")
        time.sleep(0.5)


@pytest.fixture(scope="session")
def http() -> requests.Session:
    with requests.Session() as sesion:
        yield sesion


@pytest.fixture(scope="session")
def esquema_publicado(url_api, http) -> dict:
    """El contrato tal como lo publica el PROVEEDOR (GET /esquema)."""
    return http.get(f"{url_api}/esquema", timeout=5).json()


@pytest.fixture(scope="session")
def esquema_del_consumidor() -> dict:
    """La copia del contrato que el CONSUMIDOR tiene versionada en el repositorio."""
    return json.loads(ESQUEMA_DEL_CONSUMIDOR.read_text(encoding="utf-8"))
