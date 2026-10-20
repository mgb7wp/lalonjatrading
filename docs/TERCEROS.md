# Código de terceros

Partes de La Lonja están adaptadas de proyectos de código abierto. Cada una se
cita aquí con su licencia, y en el propio fichero adaptado.

## Vibe-Trading (HKUDS)

- **Origen:** <https://github.com/HKUDS/Vibe-Trading>
- **Licencia:** MIT (abajo, tal cual).
- **Qué se ha adaptado:**

| Fichero de La Lonja | Origen en Vibe-Trading | Qué se tomó |
|---|---|---|
| `core/estrategia/datos/tiingo_proveedor.py` | `agent/backtest/loaders/tiingo_loader.py` | Formato de la respuesta de Tiingo y la regla de no mezclar barras ajustadas con barras sin ajustar en una misma serie |
| `core/estrategia/datos/b3_proveedor.py` | `agent/src/br_data/cotahist.py` | Posiciones de los campos del fichero COTAHIST de la B3 y reglas de lectura (decimales implícitos, factor de cotización, solo reales) |

El código se ha reescrito sobre el contrato de fuentes de este proyecto
(`core/estrategia/datos/proveedor.py`); no se copia ningún fichero entero.

```
MIT License

Copyright (c) 2026 Vibe-Trading Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
