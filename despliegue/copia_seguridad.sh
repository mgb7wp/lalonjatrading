#!/usr/bin/env bash
# Copia de seguridad de Postgres, con restauracion verificada.
#
#   ./despliegue/copia_seguridad.sh              # en el servidor, via Docker
#   ./despliegue/copia_seguridad.sh --local      # contra un Postgres local (pruebas)
#   ./despliegue/copia_seguridad.sh --restaurar FICHERO   # recuperar de verdad
#
# **La verificacion no es opcional y por eso va dentro.** Un volcado que nadie ha
# restaurado nunca no es una copia de seguridad: es un fichero. El caso que
# importa —pg_dump que termina con exito y produce algo irrecuperable— no lo
# detecta ningun `echo $?`. Aqui cada copia se restaura en una base de usar y
# tirar y se comprueba que las filas estan, antes de darla por buena y antes de
# rotar las anteriores.
#
# Orden deliberado: primero verificar, despues rotar. Al reves, una copia mala
# podria empujar fuera a la ultima buena.

set -euo pipefail
cd "$(dirname "$0")/.."

rojo()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
ok()    { printf '\033[32m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33m%s\033[0m\n' "$*"; }

DESTINO="${LALONJA_BACKUP_DIR:-/var/backups/lalonja}"
RETENCION="${LALONJA_BACKUP_RETENCION:-14}"

local_=0
restaurar=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)     local_=1; shift ;;
    --restaurar) restaurar="${2:-}"; shift 2 ;;
    *) rojo "Opcion desconocida: $1"; exit 1 ;;
  esac
done

if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi
USUARIO="${POSTGRES_USER:-lalonja}"
BASE="${POSTGRES_DB:-lalonja}"

# Como se habla con Postgres. Con Docker en el servidor; con los binarios del
# sistema en pruebas. Todo lo demas del script es identico en los dos casos, que
# es lo que permite probarlo sin levantar el despliegue entero.
if (( local_ )); then
  pg() { "$@"; }
else
  COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.produccion.yml)
  [[ -f docker-compose.tunel.yml ]] && COMPOSE+=(-f docker-compose.tunel.yml)
  pg() { "${COMPOSE[@]}" exec -T postgres "$@"; }
fi

# --- Restauracion real -----------------------------------------------------

if [[ -n "$restaurar" ]]; then
  if [[ ! -f "$restaurar" ]]; then
    rojo "No existe el fichero: $restaurar"
    exit 1
  fi
  aviso "Vas a SOBRESCRIBIR la base '$BASE' con $restaurar."
  aviso "Todo lo que haya ahora en ella se pierde."
  read -r -p "Escribe el nombre de la base para confirmar: " confirmacion
  if [[ "$confirmacion" != "$BASE" ]]; then
    rojo "No coincide. No se ha tocado nada."
    exit 1
  fi
  ok "Restaurando..."
  pg pg_restore -U "$USUARIO" -d "$BASE" --clean --if-exists --no-owner < "$restaurar"
  ok "Restaurada."
  exit 0
fi

# --- Copia -----------------------------------------------------------------

mkdir -p "$DESTINO"
# La copia contiene todos los datos: que no la pueda leer cualquiera del sistema.
chmod 700 "$DESTINO"

marca="$(date -u +%Y%m%dT%H%M%SZ)"
fichero="$DESTINO/lalonja-$marca.dump"

ok "Volcando $BASE..."
# `-Fc` (formato propio) y no SQL plano: comprime, y `pg_restore` puede sacar
# una sola tabla de ahi sin releer un fichero de gigabytes.
pg pg_dump -U "$USUARIO" -d "$BASE" -Fc --no-owner > "$fichero"
chmod 600 "$fichero"

tam=$(stat -c%s "$fichero" 2>/dev/null || stat -f%z "$fichero")
if (( tam < 1024 )); then
  rojo "El volcado ocupa $tam bytes: eso no es una copia de nada."
  rm -f "$fichero"
  exit 1
fi
ok "Volcado: $fichero ($(( tam / 1024 )) KB)"

# --- Verificacion: restaurar de verdad y contar ----------------------------

VERIFICACION="lalonja_verificacion_$$"
case "$VERIFICACION" in
  *verificacion*) : ;;
  # Guardarrail: este script CREA y BORRA esta base. Si el nombre no lleva
  # 'verificacion', algo ha cambiado y prefiero parar a borrar lo que no toca.
  *) rojo "nombre de base de verificacion inesperado: $VERIFICACION"; exit 1 ;;
esac

limpiar() {
  pg dropdb -U "$USUARIO" --if-exists "$VERIFICACION" >/dev/null 2>&1 || true
}
trap limpiar EXIT

ok "Verificando la copia: restaurandola en $VERIFICACION..."
pg createdb -U "$USUARIO" "$VERIFICACION"
if ! pg pg_restore -U "$USUARIO" -d "$VERIFICACION" --no-owner < "$fichero" >/dev/null 2>&1; then
  rojo "La copia NO se puede restaurar. Se conserva para diagnosticar: $fichero"
  rojo "No se ha rotado nada: la ultima copia buena sigue donde estaba."
  exit 1
fi

# Contar filas es lo que separa "el fichero se deja leer" de "los datos estan".
# Un volcado de un esquema vacio se restaura sin un solo error.
# `|| echo 0` y stderr silenciado: si la tabla no existe en la copia, eso ES el
# fallo que se esta buscando, y quiero anunciarlo con una frase entendible en
# lugar de morir con el error crudo de psql y `set -e`.
leer() {
  pg psql -U "$USUARIO" -d "$VERIFICACION" -tAc "$1" 2>/dev/null | tr -d '[:space:]' || echo 0
}
tablas=$(leer "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
valores=$(leer "SELECT count(*) FROM security")
precios=$(leer "SELECT count(*) FROM price")

if [[ "${tablas:-0}" -lt 20 ]]; then
  rojo "Solo ${tablas:-0} tablas en la copia restaurada; el esquema tiene muchas mas."
  rojo "Se conserva para diagnosticar: $fichero. No se ha rotado nada."
  exit 1
fi
if [[ "${valores:-0}" -lt 1 ]]; then
  # Comillas simples: con dobles, los acentos graves de 'security' serian
  # sustitucion de comandos y bash intentaria EJECUTAR security.
  rojo 'La copia se restaura pero no tiene ni un valor en la tabla `security`.'
  rojo "Se conserva para diagnosticar: $fichero. No se ha rotado nada."
  exit 1
fi

ok "Verificada: $tablas tablas, $valores valores, $precios precios."

# --- Rotacion --------------------------------------------------------------
# Solo ahora, con una copia buena confirmada.

sobran=$(ls -1t "$DESTINO"/lalonja-*.dump 2>/dev/null | tail -n +$((RETENCION + 1)) || true)
if [[ -n "$sobran" ]]; then
  echo "$sobran" | while read -r viejo; do
    ok "Rotando (fuera de retencion): $(basename "$viejo")"
    rm -f "$viejo"
  done
fi

# Marca para que la monitorizacion pueda saber CUANDO fue la ultima copia buena.
# Sin esto, un cron que dejo de ejecutarse no se distingue de uno que funciona.
date -u +%Y-%m-%dT%H:%M:%SZ > "$DESTINO/ultima-copia-correcta"

ok ""
ok "Listo. Copias en $DESTINO (se guardan las $RETENCION mas recientes):"
ls -1t "$DESTINO"/lalonja-*.dump | head -5
