# ds-lite

Sistema multiagente para ciencia de datos, para Claude Code. Se instala como una capa sobre un
proyecto nuevo o ya existente, añade los roles, comandos y comprobaciones que coordinan el trabajo. 

Seis roles, dos bucles de convergencia, diez comprobaciones, DVC por defecto para los datos.

## Instalar

```bash
cp -r ds-lite/. ~/code/mi-proyecto/    # sobre tu estructura ya existente, sin pisarla
cd ~/code/mi-proyecto

uv add --dev pytest ruff mypy pre-commit nbstripout dvc
pre-commit install
dvc init && dvc remote add -d storage <tu-remoto>   # S3, GCS, un disco — el que uses

gh auth status                          # obligatorio: sin gh no hay flujo
python3 setup-repo.py --new tu-org/mi-proyecto --private
# o, si el repositorio ya existe:  python3 setup-repo.py --existing

claude --agent ds-manager
> /grill-me "quiero reducir la baja de clientes"
```

## Commands, agents y skills — la distinción

Un **agent** (`.claude/agents/`) es una identidad: un prompt de sistema propio, un modelo, un conjunto de herramientas, invocado por delegación y con su propio contexto, sin memoria de la conversación principal más allá de lo que se le pase explícitamente.

### Los seis agentes

| Rol | Modelo | Hace |
|---|---|---|
| `ds-manager` | opus | Interroga hasta converger, escribe el issue, metodología en revisión y arreglos |
| `analyst` | sonnet | Puerta de datos: fugas, techo de rendimiento, estrategia de split |
| `ds-developer` | sonnet | Implementa: rojo, luego verde, un criterio cada vez. Llama a `wiki-generator` al final |
| `reviewer` | opus | Corrección de código, no metodología. Solo lectura |
| `validator` | opus | Ejecuta test/eval/metric tras converger; dirige el arreglo; el único que mira cualquier recurso de una sola mirada |
| `wiki-generator` | sonnet | Compila lo aprendido al wiki, una vez por issue |


### Los comandos, y los tres puntos donde te necesita

Un **command** (`.claude/commands/`) un procedimiento con nombre que se inserta en la conversación **actual**, con `$ARGUMENTS` sustituido. Su cuerpo puede instruir "delega en `ds-developer`, luego en `reviewer`" — el comando orquesta, el agent ejecuta.

| Comando | Qué hace | ¿Te necesita? |
|---|---|---|
| `/grill-me` | Interroga a fondo, una pregunta cada vez, con recomendación y exploración previa. Solo o dentro de `/create-issue` | Sí, es una conversación |
| `/create-issue` | Discovery ligero, puerta de datos, invoca las skills, archiva el issue | **Sí** — apruebas antes de crear nada |
| `/implement-issue` | Por criterio → integración → miradas únicas → wiki → **PR local**, de un tirón | **Sí** — confirmas la PR local antes de que toque GitHub |
| `/review-issue` | Detecta si un issue `pending` sigue vigente | Confirma antes de refrescar |
| `/update-issue` | Aplica un cambio pedido reejecutando `/create-issue` | Confirma etiquetas |

Una **skill** (`.claude/skills/`) es un procedimiento con nombre que invoca **otro rol** como metodología de referencia cuando la necesita. También se pueden insertar en la conversación **actual**, con `$ARGUMENTS` sustituido

## Qué encontrarás en el repositorio

```
CLAUDE.md                 El contrato. Único documento que hay que leer entero.
setup-repo.py             Labels, branch protection en GitHub.
.claude/
  agents/*.md             Los seis roles: quién hace el trabajo.
  commands/*.md           Los cinco comandos humanos: qué escribes tú.
  skills/*/SKILL.md       Herramientas de metodología que invoca ds-manager.
  settings.json           El hook que hace cumplir "rojo antes que verde" del TDD.
gates/                    Las diez comprobaciones — corren solas, sin necesitar un agente.
templates/                ACCEPTANCE.yaml · wiki-log.md · wiki/ (jerarquía fija de 8 páginas)
wiki/                     GitHub Wiki nativo: Home, _Sidebar, seis páginas fijas, raw/, log.md.
specs/                    La sombra ejecutable de cada issue.
experiments/              Auditorías de datos y resultados de evaluación.
evals/                    Golden sets y el ledger de miradas únicas.
```

Carpetas como `data/`, `src/`, `tests/`, `notebooks/` **no están en esta lista a propósito** — son tu proyecto, no la capa multiagente.

Tres variables de entorno ajustan dónde miran los gates si tu convención difiere de `src/`, `tests/`, `data/raw/`: `DS_SRC_DIRS`, `DS_SRC_ROOT`, `DS_IMMUTABLE_DIRS`, documentadas en `CLAUDE.md`.


## Los diez gates

Ejecutables Python con código de salida. `check.py` los corre todos; es lo mismo que ejecuta CI.

| Gate | Detecta |
|---|---|
| `py_audit` | Fugas por AST, semillas ausentes, `assert` sobre métricas en `tests/` |
| `eda_report` | Informe dirigido: AUC univariante, grupos, tiempo, nulos, centinelas |
| `traceability` | Criterios sin verificación, tests huérfanos |
| `git_audit` | Crudos, secretos, binarios grandes, orden rojo→verde, `EVAL.md` sin commit o sin issue |
| `issue_sync` | Deriva entre los issues de GitHub y `ACCEPTANCE.yaml` |
| `holdout_ledger` | Cuenta las miradas a cualquier recurso de una sola mirada y detecta si cambió |
| `convergence` | Rondas de arreglo por criterio, acumuladas entre los dos bucles |
| `wiki_lint` | Falta alguna de las seis páginas fijas, `_Sidebar` incompleto, enlaces rotos, contradicciones sin resolver |
| `tdd_guard` | Test nuevo que pasa a la primera — registrado como hook en `.claude/settings.json` |
| `check` | Todo lo anterior + ruff + mypy (opcional) + pytest |

## TDD Guard Hook

`CLAUDE.md` y varios roles incluyen en su prompt que "un test nuevo se ve fallar antes de implementar". Esto lo aseguramos en `.claude/settings.json`, que la convierte en mecánica: un hook `PostToolUse` corre `gates/tdd_guard.py` tras cada `Write`/`Edit`, y si el fichero es un test nuevo (sin rastrear por git) que pasa a la primera, bloquea con salida 2 y el mensaje vuelve al agente. 

## Dos bucles, un presupuesto de rondas

```
por criterio:  ds-developer ↔ {reviewer, ds-manager}
integración:   validator ↔ ds-developer (+ ds-manager/reviewer si toca código)
```

`gates/convergence.py` cuenta las rondas de **ambos** bucles sobre el mismo contador por
criterio. Tope por defecto: 3.

**Ningún recurso de una sola mirada se toca en ninguno de los dos bucles.** Hay dos clases: la
partición de `test` de una métrica de modelo, y el `dev`/`test` de un golden set de eval. Ambos se
registran en el mismo `gates/holdout_ledger.py`, con presupuestos de mirada independientes entre
sí — probado: un recurso puede ir por su segunda mirada mientras el otro sigue en la primera.

## Datos: DVC por defecto

```bash
dvc init
dvc remote add -d storage s3://mi-bucket/datos    # o gs://, o un disco montado, lo que uses
dvc add data/raw
git add data/raw.dvc .gitignore && git commit -m "data: versiona data/raw con DVC"
```

El puntero (pequeño, con el hash) va a git; los datos van al remoto. `dvc install
--use-pre-commit-tool` genera los hooks correctos en `.pre-commit-config.yaml` con la versión
fijada — el bloque que ya incluye este repositorio es de referencia inicial, regenéralo así en
cuanto tengas DVC instalado para no arrastrar una versión desactualizada a mano.

Esto es ortogonal al ledger de miradas: DVC versiona el dataset completo y de forma continua; el
ledger cuenta miradas a un recurso concreto dentro de un issue concreto. Ambos hashean, por
motivos distintos — no hace falta elegir entre uno u otro.

## Calidad de código: Ruff cubre Black + Flake8 + isort

`ruff format` es un reemplazo directo de Black (mismo estilo, mismo output en la práctica).
`ruff check` incluye el equivalente de las reglas de Flake8, y con el conjunto `I` activado, las
de isort. No se añaden las tres herramientas por separado: además de ser trabajo redundante,
Black y Ruff pueden discrepar en decisiones de formato de borde y acabar peleándose dentro del
mismo hook de pre-commit. `mypy` se ejecuta y se reporta pero no bloquea `check.py` por
defecto — es opcional; para hacerlo bloqueante, un solo booleano en `gates/check.py`.


