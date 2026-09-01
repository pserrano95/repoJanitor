# CLAUDE.md — RepoJanitor

## Qué es esto

Arreglador de fallos de CI agnóstico de proveedor y de modelo, policy-first,
publicado como open source (MIT) con una GitHub Action compuesta. Lee solo
ficheros aprobados, redacta credenciales, pide diagnóstico y diff
estructurado a un modelo, valida el parche contra la política del
repositorio y lo aplica en un worktree separado.

## El negocio, en cinco líneas

Proyecto abierto cuyo activo es la confianza. La promesa central — **nunca
commitea, nunca pushea, nunca abre PR, nunca fusiona, nunca ejecuta comandos
propuestos por el modelo** — es lo que lo hace adoptable. Un cambio que
debilite una frontera de seguridad debilita el producto aunque añada
función.

## Cómo se trabaja aquí

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[openai]"
python -m unittest discover -s tests -v
```

Python 3.11+. CI en 3.11 y 3.13, Linux y Windows. La suite usa solo
biblioteca estándar y Git.

## Restricciones duras

- Las promesas del README (no commit/push/PR/merge/exec) no se relajan; un
  cambio que las toque se rechaza.
- Los comandos de validación van como arrays sin shell: no introducir
  expansión de shell en ninguna ruta de ejecución.
- El contenido del repositorio analizado se trata como datos no confiables
  en el prompt; los comandos que sugiera el modelo no se ejecutan ni se
  registran como autoridad.
- El core no persiste prompts ni respuestas completos.
- En los ejemplos y docs de producción, la Action se referencia por tag o
  SHA fijado.

## Commits y PRs

Mensajes en **español**: qué cambia y por qué. Nunca se toca `main`
directamente ni se fusiona nada: rama + pull request, y la fusión la decide
el dueño del repo.

La primera línea del cuerpo del PR, en inglés y tal cual (es sintaxis de
GitHub, no idioma): `Closes #<número>`.

Todo PR cierra con estas tres líneas rellenas:

- **Qué cambia y por qué:**
- **Probado y descartado:**
- **Queda a medias:**

Si trabajando aquí descubres que algo de este archivo ya no es verdad, dilo
en el PR.
