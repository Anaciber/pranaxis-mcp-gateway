# Lanzamiento Pranaxis MCP Gateway 0.3 — lista de pasos

Orden obligado: 1 → 2 → 3 → 4 → 5. Nada público antes del paso 1.

1. **Revisión legal (Ignacio Fernández)**: licencia Apache-2.0 (sustituir LICENSE por el texto completo oficial), README
   (menciones a patentes, marca, AMD y GitHub como compatibilidad), y que el repositorio no contenga el bitstream ni RTL.
2. **GitHub**: crear el repositorio público `Anaciber/pranaxis-mcp-gateway` (el nombre del registro usa el usuario de GitHub tal cual,
   con mayúscula: `io.github.Anaciber/...`). Subir el contenido de esta carpeta. Activar Issues y Discussions.
3. **PyPI**: crear el proyecto `pranaxis-mcp-gateway` en pypi.org y configurar *trusted publishing* apuntando al repositorio
   y al workflow `publish.yml`. Alternativa manual la primera vez: `python -m build` y `twine upload dist/*` (el `dist/` ya está generado).
   El README lleva el marcador `mcp-name: io.github.Anaciber/pranaxis-mcp-gateway`, que el registro exige en el paquete.
4. **Registro oficial MCP**: instalar `mcp-publisher` (binario del repositorio modelcontextprotocol/registry),
   `mcp-publisher login github`, `mcp-publisher validate server.json`, `mcp-publisher publish server.json`.
   Comprobar: `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=pranaxis"`.
   En adelante, cada etiqueta `vX.Y.Z` publica sola en PyPI y en el registro (workflow).
5. **Anuncio**: entrada en pranaxis.eu (sección nueva "Gateway MCP" con el enlace al repositorio), LinkedIn, y una nota en las
   discusiones del repositorio de Ross de AMD (regla de Vivado) y en #openshell-dev de CNCF (misma idea, otra puerta).
   A Avnet y a Mario Ruiz, el enlace sin más comentario: ya saben lo que es.

Qué NO se publica: el bitstream, el RTL, `fam_server.py`, las medidas internas (F-Q-01) y el plan de la demo de Ross.
