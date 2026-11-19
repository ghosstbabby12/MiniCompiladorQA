#!/usr/bin/env bash
# ===========================================================================
# Despliegue con verificación y ROLLBACK automático.
#
#   ./infra/despliegue/desplegar.sh <imagen-nueva>
#
# Pasos:
#   1. Recordar qué imagen está corriendo ahora (la "anterior", conocida buena).
#   2. Detener el contenedor actual (sin borrarlo: es el seguro del rollback).
#   3. Arrancar la imagen nueva.
#   4. Verificar: healthcheck (/salud) + prueba de humo (compilar un programa
#      y comparar la salida con la esperada).
#   5a. Si pasa  → borrar el contenedor anterior. Exit 0.
#   5b. Si falla → borrar el nuevo, volver a arrancar el anterior, verificarlo.
#       Exit 1 (el pipeline queda en rojo aunque el servicio siga funcionando).
#
# Variables opcionales: NOMBRE (contenedor), PUERTO, INTENTOS (healthcheck).
# ===========================================================================
set -euo pipefail

IMAGEN_NUEVA=${1:?Uso: desplegar.sh <imagen>}
NOMBRE=${NOMBRE:-minicompilador-api}
PUERTO=${PUERTO:-8080}
INTENTOS=${INTENTOS:-15}
URL="http://127.0.0.1:${PUERTO}"

log() { printf '[desplegar] %s\n' "$*"; }

arrancar() {  # $1 = imagen
  docker run -d --name "$NOMBRE" -p "${PUERTO}:8000" \
    --read-only --tmpfs /tmp --security-opt no-new-privileges:true \
    --restart unless-stopped "$1" > /dev/null
}

verificar() {
  # Healthcheck: esperar a que /salud responda 200.
  for intento in $(seq 1 "$INTENTOS"); do
    if curl -sf "${URL}/salud" > /dev/null 2>&1; then
      log "salud OK (intento ${intento})"
      # Prueba de humo: no basta con "estar vivo", debe compilar BIEN.
      salida=$(curl -sf -X POST "${URL}/compilar" -H 'Content-Type: application/json' \
        -d '{"codigo":"int a = 6;\nprint(a * 7);"}' | grep -o '"salida":\["[^]]*\]' || true)
      if [[ "$salida" == '"salida":["42"]' ]]; then
        log "prueba de humo OK (6 * 7 = 42)"
        return 0
      fi
      log "prueba de humo FALLÓ: ${salida:-sin respuesta}"
      return 1
    fi
    sleep 2
  done
  log "salud FALLÓ tras ${INTENTOS} intentos"
  return 1
}

# 1. ¿Qué está corriendo ahora?
IMAGEN_ANTERIOR=$(docker inspect --format '{{.Config.Image}}' "$NOMBRE" 2> /dev/null || true)
log "versión actual: ${IMAGEN_ANTERIOR:-ninguna (primer despliegue)}"
log "versión nueva:  ${IMAGEN_NUEVA}"

# 2. Apartar la versión actual (detenida, no borrada).
if [[ -n "$IMAGEN_ANTERIOR" ]]; then
  docker rm -f "${NOMBRE}-anterior" > /dev/null 2>&1 || true
  docker stop "$NOMBRE" > /dev/null
  docker rename "$NOMBRE" "${NOMBRE}-anterior"
fi

# 3 y 4. Arrancar y verificar la nueva.
if arrancar "$IMAGEN_NUEVA" && verificar; then
  docker rm -f "${NOMBRE}-anterior" > /dev/null 2>&1 || true
  log "✔ DESPLIEGUE EXITOSO: ${IMAGEN_NUEVA}"
  exit 0
fi

# 5b. ROLLBACK
log "✘ la versión nueva no pasó la verificación. Logs:"
docker logs --tail 20 "$NOMBRE" 2>&1 | sed 's/^/    | /' || true
docker rm -f "$NOMBRE" > /dev/null 2>&1 || true

if [[ -z "$IMAGEN_ANTERIOR" ]]; then
  log "✘ no hay versión anterior a la cual volver (primer despliegue)."
  exit 1
fi

log "↩ ROLLBACK a ${IMAGEN_ANTERIOR}"
docker rename "${NOMBRE}-anterior" "$NOMBRE"
docker start "$NOMBRE" > /dev/null
if verificar; then
  log "↩ rollback completado: el servicio sigue en la versión anterior."
else
  log "✘✘ el rollback TAMBIÉN falló: intervención manual necesaria."
fi
exit 1
