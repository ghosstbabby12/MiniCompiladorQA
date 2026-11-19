"""Pruebas de CONFIGURACIÓN: el pipeline también es código y también se prueba.

¿Por qué? Un cambio inocente en el YAML (borrar un job, bajar el umbral de
cobertura, quitar el trigger de pull_request) desactiva la red de seguridad
del proyecto SIN que ninguna prueba del compilador falle. Estas pruebas
detectan esa regresión de configuración antes de fusionar.
"""

import tomllib
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
UMBRAL_MINIMO_COBERTURA = 85


@pytest.fixture(scope="module")
def ci() -> dict:
    texto = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return yaml.safe_load(texto)


@pytest.fixture(scope="module")
def cd() -> dict:
    texto = (RAIZ / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
    return yaml.safe_load(texto)


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with open(RAIZ / "pyproject.toml", "rb") as archivo:
        return tomllib.load(archivo)


def disparadores(workflow: dict) -> dict:
    # Detalle de YAML 1.1: la clave 'on' se lee como el booleano True.
    return workflow.get("on", workflow.get(True))


def comandos(job: dict) -> str:
    return "\n".join(paso.get("run", "") for paso in job["steps"])


def test_ci_se_dispara_en_push_y_pull_request(ci):
    # Arrange / Act
    eventos = disparadores(ci)

    # Assert
    assert "push" in eventos
    assert "pull_request" in eventos


def test_ci_tiene_los_cuatro_jobs(ci):
    # Arrange / Act
    jobs = set(ci["jobs"])

    # Assert
    assert {"lint", "tests", "sonar", "docker", "infra"} <= jobs


@pytest.mark.parametrize("job", ["sonar", "docker", "infra"])
def test_jobs_costosos_dependen_de_lint_y_tests(ci, job):
    # Arrange / Act
    dependencias = set(ci["jobs"][job]["needs"])

    # Assert
    assert dependencias == {"lint", "tests"}


def test_lint_revisa_reglas_y_formato(ci):
    # Arrange / Act
    texto = comandos(ci["jobs"]["lint"])

    # Assert
    assert "ruff check" in texto
    assert "ruff format --check" in texto


def test_quality_gate_de_cobertura_activo(pyproject):
    # Arrange
    opciones = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    # Act
    umbral = next(int(o.split("=")[1]) for o in opciones if o.startswith("--cov-fail-under="))

    # Assert: valor límite, nadie puede bajarlo de 85 sin que esta prueba falle.
    assert umbral >= UMBRAL_MINIMO_COBERTURA


def test_job_tests_ejecuta_pytest_sin_desactivar_el_gate(ci):
    # Arrange / Act
    texto = comandos(ci["jobs"]["tests"])

    # Assert: pytest usa la configuración de pyproject (con el gate).
    assert "pytest" in texto
    assert "--no-cov" not in texto
    assert "--cov-fail-under=0" not in texto


def test_job_docker_corre_las_pruebas_de_contrato(ci):
    # Arrange / Act
    texto = comandos(ci["jobs"]["docker"])

    # Assert
    assert "--exit-code-from test-runner" in texto


def test_secretos_no_estan_escritos_en_el_workflow(ci):
    # Arrange
    sonar = ci["jobs"]["sonar"]

    # Act
    token = sonar["env"]["SONAR_TOKEN"]

    # Assert: viene de GitHub Secrets, nunca como texto literal.
    assert token == "${{ secrets.SONAR_TOKEN }}"


def test_permisos_minimos_del_token(ci):
    # Arrange / Act
    permisos = ci["permissions"]

    # Assert
    assert permisos == {"contents": "read"}


def test_sonar_apunta_a_la_cobertura_generada_en_ci():
    # Arrange
    propiedades = dict(
        linea.split("=", 1)
        for linea in (RAIZ / "sonar-project.properties").read_text(encoding="utf-8").splitlines()
        if linea and not linea.startswith("#")
    )

    # Act / Assert
    assert propiedades["sonar.sources"] == "src"
    assert propiedades["sonar.python.coverage.reportPaths"] == "coverage.xml"
    assert propiedades["sonar.qualitygate.wait"] == "true"


# ---------------------------------------------------------------------------
# CD
# ---------------------------------------------------------------------------


def test_cd_solo_despliega_si_ci_paso(cd):
    # Arrange
    eventos = disparadores(cd)

    # Act
    condicion = cd["jobs"]["publicar"]["if"]

    # Assert
    assert eventos["workflow_run"]["workflows"] == ["CI"]
    assert "workflow_run.conclusion == 'success'" in condicion


def test_cd_usa_secrets_para_el_registro(cd):
    # Arrange
    login = next(p for p in cd["jobs"]["publicar"]["steps"] if "login-action" in p.get("uses", ""))

    # Act / Assert
    assert login["with"] == {
        "username": "${{ secrets.DOCKERHUB_USERNAME }}",
        "password": "${{ secrets.DOCKERHUB_TOKEN }}",
    }


def test_cd_despliega_con_el_script_de_rollback_y_luego_promueve(cd):
    # Arrange
    pasos = [p.get("name", "") for p in cd["jobs"]["desplegar"]["steps"]]
    texto = comandos(cd["jobs"]["desplegar"])

    # Act / Assert: promover a :estable va DESPUÉS de desplegar (si falla, no se promueve).
    assert "infra/despliegue/desplegar.sh" in texto
    assert pasos.index("Promover a :estable") > pasos.index("Desplegar la versión nueva")


def test_cd_no_cancela_despliegues_a_medias(cd):
    # Arrange / Act / Assert
    assert cd["concurrency"]["cancel-in-progress"] is False
