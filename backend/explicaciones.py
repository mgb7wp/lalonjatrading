"""Explicaciones con IA (FASE 16, ARCHITECTURE.md §12).

El LLM está al final de la cadena y sólo lee: recibe un JSON con lo que el motor
ya calculó y lo redacta en castellano. Las cuatro reglas duras de §12 no se
confían a la buena voluntad del modelo; cada una tiene aquí su mecanismo:

1. **No calcula números.** La entrada lleva las cifras ya redondeadas tal y como
   se pueden decir, y el prompt pide copiarlas, no derivarlas.
2. **Ante un hueco, «Información no disponible».** Los huecos viajan en la
   entrada con su motivo. El validador comprueba que la sección que
   corresponde a un hueco diga exactamente eso, y que ninguna frase hable de un
   pilar ausente sin declararlo ausente.
3. **Un validador rechaza cifras que no estaban en la entrada.** Se extraen
   todas las cifras del texto y cada una tiene que poder leerse en la entrada.
   Si una no, la respuesta entera se descarta: no se «limpia» la cifra, porque
   la frase que la llevaba estaba construida sobre ella.
4. **Caché por (valor, fecha, hash).** El hash es el de la entrada completa,
   no sólo el del score: si cambia la señal cambia lo que hay que contar. Una
   entrada que no cambia no se vuelve a explicar, y el coste crece con los
   datos, no con el tráfico.

Sin el validador, lo demás sería decoración: un prompt que dice «no inventes»
es una petición; un validador que tira la respuesta es una garantía.

Este módulo no sabe de HTTP ni de sesiones. El endpoint vive en
`api/v1/explicaciones.py` y el cliente del modelo se inyecta, para que los
tests puedan poner un redactor falso que se porte mal a propósito.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("explicaciones")

#: La frase exacta de la regla 2. Una constante, porque el validador la busca
#: literalmente y la interfaz la reconoce para pintarla como hueco.
NO_DISPONIBLE = "Información no disponible"

#: Entra en el hash. Cambiar el prompt o el esquema de la entrada invalida la
#: caché a propósito: una explicación redactada con otras instrucciones no es
#: la misma explicación.
VERSION_PROMPT = "2026-09-22.1"

IDIOMA = "es"

#: Intentos por explicación. El segundo lleva escrito por qué se rechazó el
#: primero. Más de dos es pagar por insistir en algo que no sale.
INTENTOS = 2

ETIQUETAS: dict[str, str] = {
    "overall": "Total",
    "fundamental": "Fundamental",
    "technical": "Técnico",
    "sentiment": "Sentimiento",
    "risk": "Riesgo",
    "growth": "Crecimiento",
    "profitability": "Rentabilidad",
    "financial_health": "Salud financiera",
    "quality": "Calidad",
    "valuation": "Valoración",
    "momentum": "Momentum",
    "trend": "Tendencia",
    "volatility": "Volatilidad",
    "volume": "Volumen",
}

SENALES: dict[str, str] = {
    "strong_buy": "compra fuerte",
    "buy": "compra",
    "hold": "mantener",
    "sell": "venta",
    "strong_sell": "venta fuerte",
}

MOTIVOS_SENAL: dict[str, str] = {
    "score_alto": "el score está por encima del umbral de compra",
    "score_intermedio": "el score está en la franja intermedia",
    "score_bajo": "el score está por debajo del umbral de venta",
    "limita_regimen": "limitada por el régimen del mercado",
    "limita_riesgo": "limitada por el riesgo",
    "limita_momentum": "limitada por el momentum",
    "limita_score_cayendo": "rebajada porque el score viene cayendo",
    "limita_valoracion": "limitada por la valoración",
    "datos_insuficientes": "no hay datos suficientes para emitir una señal",
}

#: Secciones de la respuesta. Coinciden con las columnas de `explanation`.
SECCIONES_LISTA = ("a_favor", "en_contra", "cambios", "preguntas")

ESQUEMA_SALIDA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        **{s: {"type": "array", "items": {"type": "string"}} for s in SECCIONES_LISTA},
    },
    "required": ["resumen", *SECCIONES_LISTA],
    "additionalProperties": False,
}

SISTEMA = f"""\
Eres el redactor de las explicaciones de La Lonja Trading, una plataforma de \
análisis cuantitativo. Recibes un JSON con los resultados que un motor \
determinista ya ha calculado para un valor cotizado, y los explicas en \
castellano claro a un inversor particular.

Reglas que no se rompen:

1. No calculas nada. Cada cifra que escribas tiene que aparecer tal cual en el \
JSON de entrada: no sumes, no restes, no redondees de otra forma, no conviertas \
a porcentaje, no estimes. Si una cifra no está en la entrada, no la escribas. \
Una respuesta con una sola cifra que no esté en la entrada se descarta entera.
2. Si un dato falta en la entrada —aparece en "no_disponible" o con \
"disponible": false— escribe exactamente «{NO_DISPONIBLE}» en su lugar. No lo \
supongas, no lo interpoles, no lo describas como neutro.
3. Los scores son percentiles dentro de una cohorte de empresas comparables: \
un 80 significa «mejor que el 80 % de su cohorte», no una nota absoluta. En \
Riesgo, 100 es el menor riesgo relativo.
4. Hablas de probabilidades y de lo que dicen los datos, nunca de certezas. No \
das recomendaciones personalizadas ni dices a nadie lo que tiene que hacer. No \
predices precios.
5. No usas conocimiento externo sobre la empresa, su sector o las noticias. \
Sólo el JSON.

Qué devuelves (JSON con este esquema exacto):

- "resumen": dos o tres frases con lo esencial: el score total y qué significa \
frente a su cohorte, y la señal si la hay (si "senal" no está disponible, \
dilo con «{NO_DISPONIBLE}»).
- "a_favor": una frase por cada factor de "a_favor" de la entrada, en el mismo \
orden. Si la lista de entrada está vacía, devuelve una lista vacía.
- "en_contra": igual, con "en_contra".
- "cambios": una frase por cada variación de "cambios_30d". Si "cambios_30d" \
tiene "disponible": false, devuelve exactamente ["{NO_DISPONIBLE}"].
- "preguntas": dos o tres preguntas, sin cifras, que el inversor podría \
investigar por su cuenta a partir de lo anterior.
"""


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def _r(v: float | None) -> float | None:
    """Redondeo de publicación. El LLM recibe lo que puede decir tal cual."""
    return None if v is None else round(float(v), 1)


def construir_entrada(
    *,
    valor: dict[str, Any],
    score: dict[str, Any],
    explicacion: dict[str, Any] | None,
    senal: dict[str, Any] | None,
    motivo_sin_senal: str | None,
    dias_cambio: int,
) -> dict[str, Any]:
    """El JSON que ve el LLM, y nada más.

    Recibe los bloques ya servidos por `/analysis` (los mismos, con el mismo
    corte temporal) y los reduce a lo que hace falta para redactar. Todo pilar
    o sub-score nulo sale de las cifras y entra en `no_disponible` con su
    motivo: un `null` suelto invitaría a rellenarlo.
    """
    pilares: dict[str, float] = {}
    subscores: dict[str, float] = {}
    no_disponible: dict[str, str] = {}
    motivos = score.get("pilares_no_disponibles") or {}
    for clave, v in (score.get("pilares") or {}).items():
        if v is None:
            no_disponible[ETIQUETAS.get(clave, clave)] = motivos.get(clave, "sin datos")
        else:
            pilares[ETIQUETAS.get(clave, clave)] = _r(v)
    for clave, v in (score.get("subscores") or {}).items():
        if v is None:
            no_disponible[ETIQUETAS.get(clave, clave)] = "sin datos suficientes"
        else:
            subscores[ETIQUETAS.get(clave, clave)] = _r(v)

    def factores(lista: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "factor": ETIQUETAS.get(f["nombre"], f["nombre"]),
                "percentil": _r(f["valor"]),
                "nivel": "pilar" if f.get("nivel") == "pilar" else "sub-score",
            }
            for f in lista
        ]

    exp = explicacion or {}
    variaciones = {ETIQUETAS.get(k, k): _r(v) for k, v in (exp.get("cambio_30d") or {}).items()}
    if variaciones:
        cambios: dict[str, Any] = {
            "disponible": True,
            "ventana_dias": dias_cambio,
            "variacion_en_puntos": variaciones,
            "no_comparables": [
                ETIQUETAS.get(k, k) for k in (exp.get("cambio_no_comparable") or [])
            ],
        }
    else:
        cambios = {
            "disponible": False,
            "motivo": f"no hay un score de hace {dias_cambio} días con el que comparar",
        }

    if senal:
        bloque_senal: dict[str, Any] = {
            "disponible": True,
            "senal": SENALES.get(senal["senal"], senal["senal"]),
            "motivo": MOTIVOS_SENAL.get(senal["motivo"], senal["motivo"]),
            "regimen_mercado": senal.get("regimen"),
            "fecha": str(senal["fecha"]),
        }
    else:
        bloque_senal = {"disponible": False, "motivo": motivo_sin_senal or "sin señal"}

    return {
        "valor": {
            "ticker": valor["ticker"],
            "nombre": valor["name"],
            "mercado": valor["market_id"],
            "sector": valor.get("sector"),
        },
        "fecha_score": str(score["fecha"]),
        "perfil": score["modelo"],
        "escala": "percentil de 0 a 100 dentro de la cohorte; en Riesgo, 100 = menor riesgo",
        "score": {
            "total": _r(score["overall"]),
            "cohorte": str(score["cohorte"]).replace("_", " "),
            "empresas_en_cohorte": score["n_cohorte"],
            "pilares": pilares,
            "subscores": subscores,
        },
        "no_disponible": no_disponible,
        "a_favor": factores(exp.get("a_favor") or []),
        "en_contra": factores(exp.get("en_contra") or []),
        "cambios_30d": cambios,
        "senal": bloque_senal,
    }


def canonico(entrada: dict[str, Any]) -> str:
    """Serialización estable: la misma entrada da siempre los mismos bytes."""
    return json.dumps(entrada, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_entrada(entrada: dict[str, Any]) -> str:
    """La clave de caché. Incluye la versión del prompt (ver `VERSION_PROMPT`)."""
    return hashlib.sha256(f"{VERSION_PROMPT}\n{canonico(entrada)}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Validador
# ---------------------------------------------------------------------------

#: Una cifra: dígitos con separadores de miles o decimales, en cualquiera de las
#: dos convenciones. El signo no se captura: «cayó 5 puntos» dice un -5 que está
#: en la entrada, y exigir el signo rechazaría la forma natural de decirlo.
_CIFRA = re.compile(r"\d+(?:[.,]\d+)*")


def _lecturas(token: str) -> set[float]:
    """Las formas razonables de leer una cifra escrita.

    «1.234» puede ser mil doscientos treinta y cuatro (castellano) o uno coma
    dos (inglés). No se adivina: se prueban las dos y basta con que una esté en
    la entrada. Es la opción permisiva, pero sólo entre lecturas de la MISMA
    cifra; ninguna lectura inventa un número que no esté escrito.
    """
    puntos, comas = token.count("."), token.count(",")
    lecturas: set[float] = set()
    if puntos == 0 and comas == 0:
        return {float(token)}
    if puntos and comas:
        # La que va última es la decimal.
        if token.rfind(",") > token.rfind("."):
            lecturas.add(float(token.replace(".", "").replace(",", ".")))
        else:
            lecturas.add(float(token.replace(",", "")))
        return lecturas
    sep = "." if puntos else ","
    if (puntos or comas) == 1:
        lecturas.add(float(token.replace(sep, ".")))
    partes = token.split(sep)
    if all(len(p) == 3 for p in partes[1:]):
        lecturas.add(float(token.replace(sep, "")))
    return lecturas


def _clave(x: float) -> float:
    return round(abs(x), 6)


def cifras_permitidas(entrada: dict[str, Any]) -> set[float]:
    """Todas las cifras que se pueden leer en la entrada.

    Cada número de la entrada vale tal cual, en valor absoluto y redondeado a
    0, 1 y 2 decimales: «75» por un 75,0 no es inventar. Además valen las
    cifras escritas dentro de los textos (la fecha, un ticker con dígitos, el
    «100» de la escala), porque también están delante del modelo.
    """
    permitidas: set[float] = set()

    def recorrer(nodo: Any) -> None:
        if isinstance(nodo, bool) or nodo is None:
            return
        if isinstance(nodo, int | float):
            for d in (0, 1, 2):
                permitidas.add(_clave(round(float(nodo), d)))
            permitidas.add(_clave(float(nodo)))
        elif isinstance(nodo, str):
            for token in _CIFRA.findall(nodo):
                permitidas.update(_clave(x) for x in _lecturas(token))
        elif isinstance(nodo, dict):
            for k, v in nodo.items():
                recorrer(k)
                recorrer(v)
        elif isinstance(nodo, list):
            for v in nodo:
                recorrer(v)

    recorrer(entrada)
    return permitidas


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def _frases(texto: str) -> list[str]:
    # Los dos puntos NO parten: «Sentimiento: Información no disponible» es una
    # sola afirmación, y partirla dejaría «Sentimiento:» sola, sin declarar.
    return [f for f in re.split(r"(?<=[.;!?])\s+|\n+", texto) if f.strip()]


@dataclass
class Validacion:
    problemas: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not self.problemas


def validar(salida: Any, entrada: dict[str, Any]) -> Validacion:
    """Decide si una respuesta del LLM se puede publicar.

    Rechaza, con el motivo escrito:

    - una forma que no sea la del esquema;
    - **cualquier cifra que no esté en la entrada** (regla 3);
    - una sección cuyo dato falta y que no dice «Información no disponible»
      (regla 2), o una frase que habla de un pilar ausente como si lo tuviera
      (salvo en las preguntas, que existen para señalar lo que no se sabe);
    - factores a favor o en contra cuando la entrada no trae ninguno: si no
      hay nada que destaque, cualquier cosa que se diga ahí es inventada.
    """
    v = Validacion()
    if not isinstance(salida, dict):
        v.problemas.append("la respuesta no es un objeto JSON")
        return v
    faltan = {"resumen", *SECCIONES_LISTA} - set(salida)
    if faltan:
        v.problemas.append(f"faltan secciones: {', '.join(sorted(faltan))}")
        return v
    sobran = set(salida) - {"resumen", *SECCIONES_LISTA}
    if sobran:
        v.problemas.append(f"sobran secciones: {', '.join(sorted(sobran))}")
    if not isinstance(salida["resumen"], str) or not salida["resumen"].strip():
        v.problemas.append("el resumen está vacío")
        return v
    for s in SECCIONES_LISTA:
        if not isinstance(salida[s], list) or not all(isinstance(x, str) for x in salida[s]):
            v.problemas.append(f"la sección {s} no es una lista de textos")
    if v.problemas:
        return v

    textos: list[tuple[str, str]] = [("resumen", salida["resumen"])]
    textos += [(s, t) for s in SECCIONES_LISTA for t in salida[s]]

    # Regla 3: ninguna cifra que no esté en la entrada.
    permitidas = cifras_permitidas(entrada)
    for seccion, texto in textos:
        for token in _CIFRA.findall(texto):
            if not any(_clave(x) in permitidas for x in _lecturas(token)):
                v.problemas.append(f"cifra que no está en la entrada: «{token}» (en {seccion})")

    # Regla 2, por secciones: el hueco se declara con la frase exacta.
    if not entrada["cambios_30d"]["disponible"] and salida["cambios"] != [NO_DISPONIBLE]:
        v.problemas.append(
            f"cambios_30d no está disponible y la sección cambios no dice «{NO_DISPONIBLE}»"
        )
    if not entrada["senal"]["disponible"] and _plano(NO_DISPONIBLE) not in _plano(
        salida["resumen"]
    ):
        v.problemas.append(f"la señal no está disponible y el resumen no dice «{NO_DISPONIBLE}»")

    # Regla 2, por frases: un pilar ausente sólo se nombra para declararlo. Las
    # preguntas quedan fuera: preguntar por lo que no se sabe es justo su papel.
    ausentes = {_plano(k) for k in entrada.get("no_disponible", {})}
    for seccion, texto in textos:
        if seccion == "preguntas":
            continue
        for frase in _frases(texto):
            plana = _plano(frase)
            if _plano(NO_DISPONIBLE) in plana or "no disponible" in plana:
                continue
            for a in ausentes:
                if re.search(rf"\b{re.escape(a)}\b", plana):
                    v.problemas.append(
                        f"habla de «{a}», que no está disponible, sin declararlo (en {seccion})"
                    )

    for s in ("a_favor", "en_contra"):
        if not entrada[s] and salida[s]:
            v.problemas.append(f"la entrada no trae factores en {s} y la respuesta sí")

    return v


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------


class ErrorRedactor(RuntimeError):
    """El modelo no respondió, se negó o respondió algo que no es JSON."""


class Redactor(Protocol):
    """Lo único que la capa necesita de un LLM. Los tests ponen uno falso."""

    modelo: str

    def redactar(self, sistema: str, mensaje: str) -> tuple[dict[str, Any], str]:
        """Devuelve la respuesta ya parseada y el modelo que la sirvió."""
        ...


class ExplicacionRechazada(RuntimeError):
    def __init__(self, problemas: list[str]):
        super().__init__("; ".join(problemas))
        self.problemas = problemas


@dataclass(frozen=True)
class Redaccion:
    resumen: str
    a_favor: list[str]
    en_contra: list[str]
    cambios: list[str]
    preguntas: list[str]
    modelo_llm: str


def _mensaje(entrada: dict[str, Any], rechazos: list[str]) -> str:
    texto = "Datos del valor (JSON):\n\n" + json.dumps(entrada, ensure_ascii=False, indent=2)
    if rechazos:
        texto += (
            "\n\nTu respuesta anterior se rechazó por estos motivos. Corrígelos sin "
            "introducir cifras nuevas:\n- " + "\n- ".join(rechazos)
        )
    return texto


def redactar(redactor: Redactor, entrada: dict[str, Any]) -> Redaccion:
    """Pide la explicación y no la devuelve hasta que el validador la acepta.

    Lanza `ExplicacionRechazada` si ningún intento pasa: lo que no se valida no
    se publica ni se guarda. Lanza `ErrorRedactor` si el modelo no responde.
    """
    rechazos: list[str] = []
    for intento in range(1, INTENTOS + 1):
        salida, servido_por = redactor.redactar(SISTEMA, _mensaje(entrada, rechazos))
        resultado = validar(salida, entrada)
        if resultado.valida:
            return Redaccion(
                resumen=salida["resumen"].strip(),
                a_favor=[t.strip() for t in salida["a_favor"]],
                en_contra=[t.strip() for t in salida["en_contra"]],
                cambios=[t.strip() for t in salida["cambios"]],
                preguntas=[t.strip() for t in salida["preguntas"]],
                modelo_llm=servido_por,
            )
        log.warning(
            "explicacion rechazada (intento %d de %d) para %s: %s",
            intento,
            INTENTOS,
            entrada["valor"]["ticker"],
            "; ".join(resultado.problemas),
        )
        rechazos = resultado.problemas
    raise ExplicacionRechazada(rechazos)


class RedactorClaude:
    """El redactor de verdad, sobre la API de Anthropic.

    - **Salida estructurada** (`output_config.format`): la forma la garantiza
      la API, así que el validador se ocupa del contenido y no de parsear.
    - **Fallback de servidor** ante una negativa del modelo: se reintenta en
      otro modelo dentro de la misma llamada. El modelo que de verdad sirvió la
      respuesta se guarda en `llm_model`.
    - **Timeout propio y reintentos del SDK** (429, 5xx y red). Un fallo aquí
      no tumba la ficha: el endpoint lo convierte en un bloque no disponible.
    """

    def __init__(self, clave: str, modelo: str, timeout: float):
        import anthropic

        self._anthropic = anthropic
        self._cliente = anthropic.Anthropic(api_key=clave, timeout=timeout, max_retries=2)
        self.modelo = modelo

    def redactar(self, sistema: str, mensaje: str) -> tuple[dict[str, Any], str]:
        anthropic = self._anthropic
        try:
            r = self._cliente.beta.messages.create(
                model=self.modelo,
                max_tokens=16000,
                system=sistema,
                messages=[{"role": "user", "content": mensaje}],
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": ESQUEMA_SALIDA},
                },
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as exc:
            raise ErrorRedactor(f"sin conexión con la API del modelo: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise ErrorRedactor("la API del modelo está limitando las peticiones") from exc
        except anthropic.APIStatusError as exc:
            raise ErrorRedactor(f"la API del modelo respondió {exc.status_code}") from exc

        if r.stop_reason == "refusal":
            raise ErrorRedactor("el modelo se negó a redactar la explicación")
        if r.stop_reason == "max_tokens":
            raise ErrorRedactor("la respuesta del modelo se cortó por longitud")
        texto = "".join(b.text for b in r.content if b.type == "text")
        try:
            return json.loads(texto), r.model
        except json.JSONDecodeError as exc:
            raise ErrorRedactor("la respuesta del modelo no es JSON") from exc
