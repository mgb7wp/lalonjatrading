"""Copias de seguridad fuera del servidor (tarea S2).

Se prueban los scripts de `despliegue/` con un `docker` de mentira en el PATH
que apunta con que argumentos le llaman. Asi se comprueba lo que importa —que
se sube la copia correcta al sitio correcto, que una subida incompleta no se da
por buena y que las claves no salen en la linea de ordenes— sin R2 ni Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

R2 = {
    "R2_ACCOUNT_ID": "cuenta123",
    "R2_BUCKET": "lalonja-copias",
    "R2_ACCESS_KEY_ID": "clave-publica",
    "R2_SECRET_ACCESS_KEY": "clave-secreta-no-mostrar",
}

#: `docker` de mentira: apunta cada llamada (un argumento por linea, llamadas
#: separadas por una linea `--`) y, a `head-object`, contesta `$TAM_REMOTO`.
DOCKER_FALSO = """#!/usr/bin/env bash
printf '%s\\n' "$@" >> "$REGISTRO"
echo -- >> "$REGISTRO"
for a in "$@"; do
  [[ "$a" == head-object ]] && { echo "$TAM_REMOTO"; exit 0; }
done
exit "${SALIDA_DOCKER:-0}"
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash")


@pytest.fixture
def entorno(tmp_path):
    """Una copia del repositorio minima: los dos scripts y un `docker` falso."""
    (tmp_path / "despliegue").mkdir()
    for nombre in ("copia_seguridad.sh", "copia_remota.sh"):
        shutil.copy2(RAIZ / "despliegue" / nombre, tmp_path / "despliegue" / nombre)
    binarios = tmp_path / "bin"
    binarios.mkdir()
    docker = binarios / "docker"
    docker.write_text(DOCKER_FALSO)
    docker.chmod(0o755)
    copias = tmp_path / "copias"
    copias.mkdir()
    registro = tmp_path / "registro"
    registro.touch()
    env = {
        "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
        "LALONJA_BACKUP_DIR": str(copias),
        "REGISTRO": str(registro),
    }
    return tmp_path, env, copias, registro


def _llamadas(registro: Path) -> list[list[str]]:
    llamadas, actual = [], []
    for linea in registro.read_text().splitlines():
        if linea == "--":
            llamadas.append(actual)
            actual = []
        else:
            actual.append(linea)
    return llamadas


def _ejecutar(raiz: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(raiz / "despliegue" / args[0]), *args[1:]],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _copia(copias: Path, contenido: bytes = b"x" * 4096) -> Path:
    f = copias / "lalonja-20260930T031500Z.dump"
    f.write_bytes(contenido)
    return f


def test_sin_r2_configurado_no_sube_nada_y_no_falla(entorno):
    """El servidor puede no tener R2 todavia: la copia local sigue valiendo."""
    raiz, env, copias, registro = entorno
    r = _ejecutar(raiz, env, "copia_remota.sh", "subir", str(_copia(copias)))
    assert r.returncode == 0, r.stderr
    assert "sin configurar" in r.stdout
    assert _llamadas(registro) == []


def test_sube_la_copia_a_su_bucket_y_comprueba_que_llego_entera(entorno):
    raiz, env, copias, registro = entorno
    copia = _copia(copias)
    env |= R2 | {"TAM_REMOTO": str(copia.stat().st_size)}
    r = _ejecutar(raiz, env, "copia_remota.sh", "subir", str(copia))
    assert r.returncode == 0, r.stderr

    subida, comprobacion = _llamadas(registro)
    assert "https://cuenta123.r2.cloudflarestorage.com" in subida
    i = subida.index("cp")
    assert subida[i + 1 : i + 3] == [
        f"/copias/{copia.name}",
        f"s3://lalonja-copias/{copia.name}",
    ]
    assert "head-object" in comprobacion
    assert (copias / "ultima-subida-correcta").exists()


def test_una_subida_incompleta_no_se_da_por_buena(entorno):
    """Que `aws s3 cp` acabe bien no dice que el fichero este entero en R2."""
    raiz, env, copias, _ = entorno
    copia = _copia(copias)
    env |= R2 | {"TAM_REMOTO": str(copia.stat().st_size - 1)}
    r = _ejecutar(raiz, env, "copia_remota.sh", "subir", str(copia))
    assert r.returncode == 1
    assert "NO vale" in r.stderr
    assert not (copias / "ultima-subida-correcta").exists()


def test_si_docker_falla_la_subida_falla(entorno):
    raiz, env, copias, _ = entorno
    env |= R2 | {"SALIDA_DOCKER": "1"}
    r = _ejecutar(raiz, env, "copia_remota.sh", "subir", str(_copia(copias)))
    assert r.returncode != 0
    assert "ha fallado" in r.stderr, "un fallo sin explicacion no se sabe arreglar"
    assert not (copias / "ultima-subida-correcta").exists()


def test_las_claves_no_van_en_la_linea_de_ordenes(entorno):
    """Con `-e VAR=valor` se verian en la lista de procesos del servidor."""
    raiz, env, copias, registro = entorno
    copia = _copia(copias)
    env |= R2 | {"TAM_REMOTO": str(copia.stat().st_size)}
    _ejecutar(raiz, env, "copia_remota.sh", "subir", str(copia))
    todo = "\n".join("\n".join(ll) for ll in _llamadas(registro))
    assert "clave-secreta-no-mostrar" not in todo
    assert "clave-publica" not in todo


def test_con_r2_sin_configurar_listar_si_falla(entorno):
    """`listar` y `bajar` se piden a mano: ahi un R2 sin configurar es un error."""
    raiz, env, _, _ = entorno
    r = _ejecutar(raiz, env, "copia_remota.sh", "listar")
    assert r.returncode == 1
    assert "R2_BUCKET" in r.stderr


@pytest.mark.parametrize(("token", "con_tunel"), [("", False), ("un-token", True)])
def test_la_copia_solo_usa_el_compose_del_tunel_si_hay_tunel(entorno, token, con_tunel):
    """El fichero del tunel esta siempre; lo que dice si se usa es el token.

    Sin tunel, pedirle a `docker compose` ese fichero lo haria quejarse de que
    falta `CLOUDFLARE_TUNNEL_TOKEN` y la copia fallaria sin empezar.
    """
    raiz, env, _, registro = entorno
    # El `docker` falso falla en la primera llamada (el volcado): basta para
    # ver con que ficheros de compose se ha invocado.
    env |= {"CLOUDFLARE_TUNNEL_TOKEN": token, "SALIDA_DOCKER": "1"}
    r = _ejecutar(raiz, env, "copia_seguridad.sh")
    assert r.returncode != 0
    primera = _llamadas(registro)[0]
    assert primera[:2] == ["compose", "-f"]
    assert ("docker-compose.tunel.yml" in primera) is con_tunel
