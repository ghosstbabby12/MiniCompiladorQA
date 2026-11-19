# syntax=docker/dockerfile:1
# ===========================================================================
# MiniCompilador QA - imagen multi-stage
#
#   constructor  instala el paquete y sus dependencias en un venv (/opt/venv).
#   contrato     cliente de pruebas de contrato (requests + jsonschema + pytest).
#   produccion   (etapa FINAL = la que se construye por defecto) solo copia el
#                venv: sin pip cache, sin código fuente ni herramientas de build.
#
# ¿Por qué multi-stage? La imagen final es más pequeña y tiene menos superficie
# de ataque: lo que no está instalado no se puede explotar.
# ===========================================================================

ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------------------
# Etapa 1: constructor
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS constructor

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# Primero solo lo necesario para instalar: si cambian las pruebas o la
# documentación, esta capa sigue en caché.
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[api,s3]"

# ---------------------------------------------------------------------------
# Etapa 2: contrato (la usa el servicio test-runner de docker-compose)
# No importa el compilador: es un consumidor HTTP externo.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS contrato

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install "pytest>=8" "requests>=2.31" "jsonschema>=4.20" \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin probador

WORKDIR /contrato
# Mismas rutas relativas que en el repositorio, así conftest.py funciona igual.
COPY tests/api ./tests/api
COPY ejemplos ./ejemplos
COPY src/minicompilador/esquemas ./src/minicompilador/esquemas

USER probador
# addopts="" ignora la configuración de cobertura de pyproject (aquí no aplica).
CMD ["pytest", "tests/api", "-o", "addopts=-ra", "-p", "no:cacheprovider", "-v"]

# ---------------------------------------------------------------------------
# Etapa 3: producción (FINAL)
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS produccion

LABEL org.opencontainers.image.title="minicompilador-api" \
      org.opencontainers.image.description="API del compilador didáctico del lenguaje Mini"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Usuario SIN privilegios: si alguien explota la API, no es root en el contenedor.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin compilador

COPY --from=constructor /opt/venv /opt/venv

USER compilador
EXPOSE 8000

# python:slim no trae curl; urllib (biblioteca estándar) basta para el chequeo.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=2)"]

CMD ["uvicorn", "minicompilador.api:app", "--host", "0.0.0.0", "--port", "8000"]
