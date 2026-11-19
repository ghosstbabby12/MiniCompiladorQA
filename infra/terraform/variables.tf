variable "endpoint_localstack" {
  description = "URL de LocalStack. En docker compose: http://localstack:4566"
  type        = string
  default     = "http://localhost:4566"
}

variable "entorno" {
  description = "Nombre del entorno (se refleja en las etiquetas)"
  type        = string
  default     = "desarrollo"

  validation {
    condition     = contains(["desarrollo", "pruebas", "produccion"], var.entorno)
    error_message = "entorno debe ser desarrollo, pruebas o produccion."
  }
}
