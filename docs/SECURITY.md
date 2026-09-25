# Seguridad

Lo que hay hoy, no lo que se pretende tener. Cuando algo esté pendiente, lo dice.

## Contraseñas

**Argon2id**, con el perfil que recomienda OWASP: 19 MiB de memoria, 2
iteraciones, 1 hilo. Los parámetros van escritos y no por defecto, porque son
exactamente la diferencia entre un hash caro y uno decorativo.

Argon2id y no bcrypt porque bcrypt solo castiga tiempo de CPU, y una GPU tiene
miles de núcleos. Argon2 exige **memoria**, que es lo que una GPU no puede
multiplicar barato.

Mínimo **12 caracteres**, sin exigir símbolos. La longitud es lo que encarece un
ataque; exigir símbolos empuja a la gente hacia `Passw0rd!`, que es corta y está
en todos los diccionarios.

Al iniciar sesión correctamente se comprueba si el hash se hizo con parámetros
más débiles que los actuales y, si es así, se recifra. Eso permite subir el coste
sin pedirle a nadie que cambie de contraseña.

## Tokens

JWT firmados con HS256. **Cada token declara su propósito** (`acceso`,
`refresco`, `reinicio`) y se verifica al leerlo. Sin esa comprobación, el token
de refresco —el de vida larga, el que se guarda en disco— valdría para llamar a
cualquier endpoint, y el de reinicio de contraseña —que viaja por correo, el
canal menos seguro— serviría para todo.

| Token | Vida | Revocable |
|---|---|---|
| Acceso | 30 min (`JWT_MINUTOS`) | No: es sin estado, por eso dura poco |
| Refresco | 30 días | Sí, lista negra en Redis |
| Reinicio | 30 min | Sí, y es de **un solo uso** |

**Rotación en el refresco:** al renovar, el token usado se revoca. Si alguien
roba uno y lo usa, el legítimo deja de funcionar y el robo se nota. Sin
rotación, los dos conviven y nadie se entera.

## No se puede averiguar quién tiene cuenta

Un endpoint que responde distinto según si la cuenta existe es una lista de
clientes descargable a razón de una petición por correo. Y para la víctima de
una filtración de otro sitio, saber que aquí también tiene cuenta es justo el
dato que faltaba.

- **Login:** misma respuesta y mismo código para «ese correo no existe» y
  «contraseña incorrecta».
- **Tiempo constante:** cuando el correo no existe se verifica igualmente contra
  un hash señuelo. Si un correo inexistente respondiera en 2 ms y uno real en los
  90 ms que cuesta Argon2, el propio reloj delataría cuáles existen.
- **Reinicio de contraseña:** responde 202 siempre.
- **Registro:** devuelve 409 sin decir que el correo ya está dado de alta.

## Limitación de peticiones

En Redis, no en memoria: con dos procesos de uvicorn un contador en memoria
permite el doble de intentos del que dice permitir.

| Endpoint | Límite |
|---|---|
| `POST /auth/login` | 10 cada 5 minutos por IP |
| `POST /auth/register` | 5 por hora por IP |
| `POST /auth/password-reset` | 5 por hora por IP |

**Falla cerrado.** Si Redis no responde, la petición se rechaza con 503 en lugar
de dejarla pasar. Un limitador que se apaga solo cuando su dependencia cae es lo
que no quieres el día que alguien tumba Redis a propósito: la barra libre para
probar contraseñas llegaría justo cuando menos se mira. El coste es que un fallo
de Redis tira el login, y se acepta a sabiendas.

La IP se toma de `X-Forwarded-For` **porque delante hay un proxy inverso
nuestro** (Caddy, y Cloudflare en producción). Sin un proxy de confianza delante,
esa cabecera la escribe cualquiera y el límite se saltaría cambiándola.

## Límites de plan

En `backend/limites.py`, en un **único diccionario**, aplicados con una única
dependencia. Repartidos por los endpoints, el día que PRO pase de 5 a 10 carteras
habría que encontrar los siete sitios donde estaba escrito, y el que se olvide
sería el que nadie mira.

Un plan desconocido cae a **FREE**, nunca a «sin límite»: equivocarse hacia el
lado restrictivo cuesta una queja; hacia el otro, una factura.

FREE tiene **cero** explicaciones de IA al día. Cada una cuesta dinero real en
tokens, y §50 pone el control de coste como restricción, no como aspiración.
En PRO y PREMIUM el cupo cuenta explicaciones **generadas**, no leídas: una
servida desde la caché no cuesta nada y no lo gasta. El contador vive en Redis,
se descuenta antes de llamar al modelo y falla cerrado igual que el limitador.

## Secretos

Ninguno en el repositorio. `.env` está en `.gitignore` con negación explícita
para las plantillas, y hay un test que falla si aparece.

`JWT_SECRET` no tiene valor por defecto utilizable: **la API se niega a arrancar
en producción sin él**. Que falle al desplegar y no cuando alguien intente
autenticarse.

## Lo que NO está hecho

- **Verificación de correo.** `email_verified_at` existe en el esquema y no se
  usa todavía.
- **Envío de correo**, que es la FASE 15. Sin él no hay forma segura de entregar
  un enlace de reinicio: en producción no se emite, y fuera de producción el
  token se registra en el log. Registrarlo en producción lo dejaría en texto
  claro a disposición de cualquiera con acceso a los logs.
- **Segundo factor.**
- **Cabeceras de seguridad HTTP**: las pone Caddy (HSTS, `X-Frame-Options`,
  `nosniff`), no la aplicación.
- **Auditoría de accesos.** Solo se guarda `last_login_at`.
- **Rotación de `JWT_SECRET`.** Cambiarlo hoy invalida todas las sesiones de
  golpe; no hay soporte para dos claves conviviendo.
