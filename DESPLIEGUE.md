# Despliegue

Dos cosas distintas, en dos sitios distintos:

| Qué | Dónde vive | Disponibilidad |
|---|---|---|
| **Informe semanal** (HTML estático) | Cloudflare Pages, dominio principal | Siempre. Es un fichero en la CDN, sin nada ejecutándose detrás. |
| **Panel interactivo** (Streamlit) | Tu máquina, expuesta por Cloudflare Tunnel | Solo mientras esa máquina esté encendida. |

Nada de esto se ha podido probar desde el entorno donde se desarrolló: su
política de red bloquea Cloudflare igual que bloquea Yahoo Finance. Lo que sigue
está escrito contra la documentación de Cloudflare, y la primera ejecución es la
que dirá si algo no encaja.

---

## Antes de empezar: el panel va a quedar público

El informe estático siendo público no tiene ningún problema: es HTML servido por
la CDN de Cloudflare, sin cómputo detrás, y lleva el descargo en la cabecera.

El panel es otra cosa y conviene tenerlo claro antes de abrirlo:

- Es **Streamlit sin autenticación**, y el túnel apunta a **tu propia máquina**.
- Enseña tus posiciones abiertas y las señales de la semana.
- Cualquiera que dé con la URL puede usarlo.

Lo que ya está hecho para mitigarlo:

- **`panel.modo_publico: true`** en `config/reglas.yaml` desactiva el botón del
  análisis de sensibilidad. Eran unos treinta backtests, o sea varios minutos de
  CPU por pulsación: dejarlo abierto a internet es regalar un botón de
  «ocúpame el ordenador». El análisis sigue disponible con `estrategia validar`,
  y el panel muestra el último resultado guardado.
- El panel **solo lee** resultados ya calculados. No escribe nada ni acepta
  entradas que lleguen al sistema de ficheros.
- Las rutas locales no se muestran en los mensajes.

Lo que conviene añadir en el panel de Cloudflare, y está explicado abajo: una
**regla de límite de peticiones** sobre el subdominio del panel.

Si en algún momento prefieres cerrarlo, **Cloudflare Access** son dos clics y no
hay que tocar el código: está al final de este documento.

---

## 1. El informe en Cloudflare Pages

### Crear el proyecto

`wrangler pages deploy` necesita que el proyecto exista antes. Una sola vez:

```bash
npm install -g wrangler
wrangler login
wrangler pages project create app-trading --production-branch claude/modest-wozniak-6uzjeq
```

O desde el panel: **Workers & Pages → Create → Pages → Direct Upload**, con el
nombre `app-trading`. Si eliges otro nombre, cámbialo también en
`--project-name` dentro de `.github/workflows/semanal.yml`.

### Primer despliegue a mano

```bash
estrategia informe --periodo todo --formato html   # genera sitio/
wrangler pages deploy sitio --project-name=app-trading
```

### El dominio

En **Workers & Pages → app-trading → Custom domains → Set up a custom domain**,
escribe tu dominio. Cloudflare crea el registro DNS solo, porque el dominio ya
está en tu cuenta.

### El token para GitHub Actions

En **My Profile → API Tokens → Create Token → Custom token**, con los permisos
mínimos:

| Tipo | Recurso | Permiso |
|---|---|---|
| Account | Cloudflare Pages | Edit |

Nada más. Un token de Pages no necesita tocar DNS ni Workers ni zonas.

Y en el repositorio, **Settings → Secrets and variables → Actions**:

| Secreto | De dónde sale |
|---|---|
| `CLOUDFLARE_API_TOKEN` | el token que acabas de crear |
| `CLOUDFLARE_ACCOUNT_ID` | panel de Cloudflare, barra derecha de la vista general |
| `EODHD_API_KEY` | solo si usas EODHD como fuente de fundamentales |

---

## 2. El panel por Cloudflare Tunnel

### Crear el túnel

```bash
# Instalar (macOS)
brew install cloudflared
# Linux: https://pkg.cloudflare.com

cloudflared tunnel login
cloudflared tunnel create app-trading
```

El segundo comando imprime el **ID del túnel** y deja un fichero de credenciales
en `~/.cloudflared/<ID>.json`. Copia la plantilla y rellénala:

```bash
cp despliegue/cloudflared/config.yml ~/.cloudflared/config.yml
# Sustituye TUNEL_ID, USUARIO y TU-DOMINIO
```

### Apuntar el subdominio

```bash
cloudflared tunnel route dns app-trading panel.TU-DOMINIO.com
```

### Arrancarlo

```bash
# Primero el panel
streamlit run panel/app.py --server.port 8501 --server.headless true

# En otra terminal, el tunel
cloudflared tunnel run app-trading
```

### Que sobreviva a un reinicio

En macOS y Linux, `cloudflared` se instala como servicio del sistema:

```bash
sudo cloudflared service install
```

El panel también tiene que arrancar solo. En Linux, con systemd
(`~/.config/systemd/user/panel-trading.service`):

```ini
[Unit]
Description=Panel de la estrategia
After=network.target

[Service]
WorkingDirectory=/ruta/al/repo
ExecStart=/ruta/al/repo/.venv/bin/streamlit run panel/app.py \
  --server.port 8501 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now panel-trading
loginctl enable-linger $USER   # para que siga sin sesión iniciada
```

En macOS, el equivalente es un `launchd` plist en `~/Library/LaunchAgents/`.

### Límite de peticiones

En **Security → WAF → Rate limiting rules**, sobre el subdominio del panel:

- **Si**: `Hostname` igual a `panel.TU-DOMINIO.com`
- **Contando**: peticiones de la misma IP
- **Cuando supere**: 60 peticiones en 1 minuto
- **Entonces**: bloquear durante 10 minutos

Streamlit hace bastantes peticiones por interacción, así que un límite más
estrecho molestaría al uso normal. Esto no impide que alguien mire; impide que
alguien insista.

---

## 3. Si prefieres cerrar el panel

**Zero Trust → Access → Applications → Add an application → Self-hosted**:

- Dominio: `panel.TU-DOMINIO.com`
- Política: *Allow*, con `Emails` y tu dirección

A partir de ahí, entrar pide un código de un solo uso al correo. Es gratis hasta
50 usuarios y no hay que tocar una línea de código: el panel no se entera.

Si haces esto, puedes poner `panel.modo_publico: false` en `config/reglas.yaml`
y recuperar el botón del análisis de sensibilidad.

---

## 4. El ciclo semanal

`.github/workflows/semanal.yml` corre los lunes a las 07:30 UTC, con el cierre
del viernes ya dentro en los cinco mercados. Hace, en este orden:

1. **Tests.** Si fallan, se para ahí: mejor el informe de la semana pasada que
   uno generado por un commit roto.
2. **Diagnóstico** de fuentes, que informa pero no corta.
3. **Descarga** de datos reales.
4. **Foto semanal** de fundamentales y divisas. Se escribe en un directorio
   temporal y solo se mueve a su sitio si termina entera.
5. **Informe** en Markdown y HTML.
6. **Commit** de la foto y del sitio.
7. **Despliegue** a Cloudflare Pages.

Se puede lanzar a mano desde la pestaña **Actions → Ciclo semanal → Run
workflow**, y ahí se puede forzar una sola fuente o desactivar la publicación.

### Por qué se versionan las fotos

`datos/fotos/` está fuera del `.gitignore` a propósito. El documento pide guardar
cada semana una copia de los fundamentales y del tipo de cambio con su fecha de
descarga, para ir construyendo un histórico sin sesgo de anticipación. El
historial de git es exactamente eso: una prueba fechada y difícil de falsear de
cuándo se capturó cada dato.

Eso importa porque hoy el 100% de los datos fundamentales es *reconstruido* —
cifras de hoy, reexpresadas, con la fecha de publicación estimada—. Cada foto
semanal es un dato *capturado* de verdad. Dentro de tres años habrá un histórico
propio que ningún proveedor puede vender.

`datos/cache/` sí se ignora: es grande y se regenera solo.

---

## La primera ejecución

Es la primera vez que este sistema toca datos reales. Lo primero que conviene
hacer, antes que nada:

```bash
estrategia --proveedor yfinance diagnostico --anos 8 --detalle
```

Devuelve, ticker a ticker, qué resuelve y qué no: series de precios que faltan,
sectores que el mapeo no conoce, campos financieros vacíos, y empresas que
reportan en una divisa distinta de la de su cotización. Está pensado para que
esa primera vez dé una lista de cosas que arreglar y no una traza.

Lo más probable es que haya que tocar:

- **`config/universo.yaml`** — los 140 tickers son una lista de partida sin
  verificar. Alguno habrá cambiado de ticker o de mercado principal.
- **`config/implementacion.yaml`** — sectores que Yahoo devuelve y el mapeo no
  conoce. El diagnóstico imprime el bloque YAML que hay que pegar.
- **`config/impuestos_transaccion.yaml`** — las listas del ITF español están sin
  contrastar con la fuente oficial.

Y presta atención a la sección de **Valoración (EV/EBIT)** del diagnóstico. Si
sale que muchos valores no tienen EV calculable, la mitad del peso de la
puntuación fundamental no está haciendo nada, y el ranking lo está decidiendo
solo la calidad. Es exactamente el fallo que tuvo este repositorio hasta que se
añadió esa comprobación.
