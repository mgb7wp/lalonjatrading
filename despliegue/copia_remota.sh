#!/usr/bin/env bash
# Copias de seguridad FUERA del servidor, en Cloudflare R2.
#
#   ./despliegue/copia_remota.sh subir FICHERO   # lo llama copia_seguridad.sh
#   ./despliegue/copia_remota.sh listar          # que copias hay en R2
#   ./despliegue/copia_remota.sh bajar NOMBRE    # traer una a LALONJA_BACKUP_DIR
#
# Las copias locales protegen de un borrado o de una migracion que sale mal,
# pero no de perder el servidor: viven en su mismo disco. Esto las saca.
#
# Configuracion, en `.env` (ver .env.produccion.example):
#   R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
# Sin ellas `subir` no hace nada y lo dice, sin fallar: la copia local sigue
# siendo buena y el servidor puede no tener R2 configurado todavia.
#
# No hace falta instalar nada: se usa la CLI oficial de AWS (R2 habla el mismo
# protocolo que S3) dentro de su imagen de Docker, que ya esta en el servidor.
#
# La antiguedad de lo que se guarda en R2 la decide una regla de ciclo de vida
# del bucket, no este script: asi el token no necesita borrar nada y una copia
# que falla no puede empujar fuera a las buenas.

set -euo pipefail
cd "$(dirname "$0")/.."

rojo()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
ok()    { printf '\033[32m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33m%s\033[0m\n' "$*"; }

if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi
DESTINO="${LALONJA_BACKUP_DIR:-/var/backups/lalonja}"
IMAGEN="${LALONJA_AWS_CLI_IMAGEN:-amazon/aws-cli:latest}"

accion="${1:-}"
arg="${2:-}"

faltan=()
for var in R2_ACCOUNT_ID R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
  [[ -n "${!var:-}" ]] || faltan+=("$var")
done
if (( ${#faltan[@]} )); then
  if [[ "$accion" == "subir" ]]; then
    aviso "R2 sin configurar (faltan en .env: ${faltan[*]}): la copia se queda solo en este servidor."
    exit 0
  fi
  rojo "R2 sin configurar. Faltan en .env: ${faltan[*]}"
  exit 1
fi

# Las claves van por el entorno y no en la linea de ordenes: `-e VAR=valor` las
# dejaria a la vista de cualquiera que mire la lista de procesos.
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# `aws` dentro de Docker, con la carpeta de copias montada en /copias.
# Los dos WHEN_REQUIRED: las versiones recientes de la CLI anaden sumas de
# comprobacion que no todos los servicios compatibles con S3 aceptan; con esto
# solo se mandan cuando la operacion las exige.
aws() {
  docker run --rm \
    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    -e AWS_DEFAULT_REGION=auto \
    -e AWS_REQUEST_CHECKSUM_CALCULATION=WHEN_REQUIRED \
    -e AWS_RESPONSE_CHECKSUM_VALIDATION=WHEN_REQUIRED \
    -v "$DESTINO":/copias \
    "$IMAGEN" --endpoint-url "$ENDPOINT" "$@"
}

case "$accion" in
  subir)
    if [[ -z "$arg" || ! -f "$arg" ]]; then
      rojo "No existe el fichero: ${arg:-(ninguno)}"
      exit 1
    fi
    nombre="$(basename "$arg")"
    if [[ "$(cd "$(dirname "$arg")" && pwd)" != "$(mkdir -p "$DESTINO" && cd "$DESTINO" && pwd)" ]]; then
      rojo "La copia tiene que estar en $DESTINO (es lo que se monta en Docker): $arg"
      exit 1
    fi
    ok "Subiendo $nombre a R2 ($R2_BUCKET)..."
    if ! aws s3 cp "/copias/$nombre" "s3://$R2_BUCKET/$nombre" --only-show-errors; then
      rojo "La subida a R2 ha fallado (mira el error de arriba). La copia local sigue en $arg."
      exit 1
    fi

    # Que el comando termine bien no dice que el fichero este entero alli. Se
    # pregunta a R2 cuanto ocupa lo que tiene y se compara con lo que se mando.
    local_tam=$(stat -c%s "$arg" 2>/dev/null || stat -f%z "$arg")
    remoto_tam=$(aws s3api head-object --bucket "$R2_BUCKET" --key "$nombre" \
      --query ContentLength --output text | tr -d '[:space:]')
    if [[ "$remoto_tam" != "$local_tam" ]]; then
      rojo "En R2 hay $remoto_tam bytes y la copia tiene $local_tam: la subida NO vale."
      exit 1
    fi
    date -u +%Y-%m-%dT%H:%M:%SZ > "$DESTINO/ultima-subida-correcta"
    ok "En R2: $nombre ($(( local_tam / 1024 )) KB), comprobado."
    ;;
  listar)
    aws s3 ls "s3://$R2_BUCKET/" --human-readable
    ;;
  bajar)
    if [[ -z "$arg" ]]; then
      rojo "Falta el nombre de la copia. Mira cuales hay con: $0 listar"
      exit 1
    fi
    mkdir -p "$DESTINO"
    chmod 700 "$DESTINO"
    aws s3 cp "s3://$R2_BUCKET/$(basename "$arg")" "/copias/$(basename "$arg")" --only-show-errors
    chmod 600 "$DESTINO/$(basename "$arg")"
    ok "Bajada: $DESTINO/$(basename "$arg")"
    ok "Para restaurarla: ./despliegue/copia_seguridad.sh --restaurar $DESTINO/$(basename "$arg")"
    ;;
  *)
    rojo "Uso: $0 subir FICHERO | listar | bajar NOMBRE"
    exit 1
    ;;
esac
