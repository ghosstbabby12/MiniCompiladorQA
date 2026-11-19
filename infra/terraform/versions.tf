# Versiones fijadas: el mismo código produce la misma infraestructura hoy y
# dentro de seis meses (el archivo .terraform.lock.hcl fija los hashes).
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      # Fijado a 5.70.x a propósito: versiones más nuevas del provider esperan un
      # campo del ciclo de vida que LocalStack 3.8 no devuelve, y el apply se
      # queda esperando 3 minutos hasta fallar. Subir ambas versiones juntas.
      version = "~> 5.70.0"
    }
  }
}
