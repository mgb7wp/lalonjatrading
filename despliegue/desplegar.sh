#!/usr/bin/env bash
# Despliegue en el servidor. Idempotente: se puede ejecutar en cada release.
#
#   ./despliegue/desplegar.sh           # VPS con IP publica: Caddy hace el TLS
#   ./despliegue/desplegar.sh --tunel   # via Cloudflare Tunnel, sin IP publica
#
# Comprueba antes de tocar nada, porque un fallo a medias deja el sitio caido y
# el mensaje de error de Docker no dice cual de las diez cosas falta.

set -euo pipefail
cd "$(dirname "$0")/.."

rojo() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }

tunel=0
case "${1:-}" in
  --tunel) tunel=1 ;;
  "") ;;
  *) rojo "Opcion desconocida: $1 (solo se admite --tunel)"; exit 1 ;;
esac

# --- Comprobaciones previas ------------------------------------------------

if [[ ! -f .env ]]; then
  rojo "Falta .env. Copia la plantilla y rellenala:"
  rojo "    cp .env.produccion.example .env"
  exit 1
fi

set -a; . ./.env; set +a

requeridas=(DOMINIO POSTGRES_PASSWORD JWT_SECRET)
if (( tunel )); then
  # Con tunel el certificado lo emite Cloudflare, asi que ACME_EMAIL no pinta
  # nada; lo que hace falta es el token del tunel.
  requeridas+=(CLOUDFLARE_TUNNEL_TOKEN)
else
  requeridas+=(ACME_EMAIL)
fi

for var in "${requeridas[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    rojo "Falta $var en .env"
    exit 1
  fi
done

# Compose necesita 2.24 o mas nuevo para la etiqueta !override que usa el
# fichero de produccion. Con una version anterior el despliegue arranca con la
# configuracion de desarrollo —puertos de Postgres abiertos a Internet
# incluidos— sin avisar de nada. Prefiero que no arranque.
version=$(docker compose version --short 2>/dev/null || echo 0)
mayor=${version%%.*}
resto=${version#*.}; menor=${resto%%.*}
if (( mayor < 2 )) || { (( mayor == 2 )) && (( menor < 24 )); }; then
  rojo "Docker Compose $version es demasiado antiguo (hace falta 2.24+)."
  rojo "Actualiza con:  curl -fsSL https://get.docker.com | sh"
  exit 1
fi

# --- Despliegue ------------------------------------------------------------

ficheros=(-f docker-compose.yml -f docker-compose.produccion.yml)
(( tunel )) && ficheros+=(-f docker-compose.tunel.yml)

compose() {
  docker compose "${ficheros[@]}" "$@"
}

ok "Construyendo imagenes..."
compose build

ok "Levantando servicios..."
compose up -d --remove-orphans

ok "Esperando a que la API responda..."
for _ in $(seq 1 60); do
  if compose exec -T api curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1; then
    ok "API viva."
    break
  fi
  sleep 2
done

ok "Limpiando imagenes antiguas..."
docker image prune -f >/dev/null

compose ps
ok ""
ok "Listo. En un minuto deberia responder https://$DOMINIO"
# Que el mensaje de ayuda traiga el comando exacto, con los mismos ficheros que
# se acaban de usar: reconstruirlo a mano es donde se olvida un -f y los logs
# que salen son los de otra cosa.
cmd="docker compose ${ficheros[*]} logs -f"
if (( tunel )); then
  ok "Si no responde, mira los logs del tunel:  $cmd cloudflared"
  ok "y comprueba en el panel de Cloudflare que la ruta publica apunta a http://caddy:80"
else
  ok "Si no responde, mira los logs de Caddy:  $cmd caddy"
  ok "El fallo mas comun es tener el DNS en naranja: el reto de Let's Encrypt no llega."
fi
