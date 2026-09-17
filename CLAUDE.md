# CLAUDE.md — contrato de trabajo

Instrucciones para Claude Code en este repositorio. Es el único documento que hay que leer
entero. Los roles están en `.claude/agents/`, los comandos en `.claude/commands/`, las skills en
`.claude/skills/`, las comprobaciones en `gates/`.

## La idea

Esta idea surge debido a la complejidad de realizar un buen proyecto de ciencia de datos, con código que sigue buenas prácticas y un resultado válido. 

Una pipeline puede correr limpio, pasar todos los tests y producir un modelo inútil porque una columna traía información del futuro. Todo lo que sigue existe para que esa diferencia la detecte una máquina.

## Esto es la capa multiagente, no una plantilla de proyecto

Este sistema no crea `data/`, `src/`, `tests/` ni ningún otro directorio de tu proyecto. El sistema se adapta a estas carpetas según el proyecto en cuestión, no al revés. Tres variables de entorno ajustan dónde miran los gates si no usas las convenciones por defecto:

| Variable | Por defecto | Qué ajusta |
|---|---|---|
| `DS_SRC_DIRS` | `src,tests,experiments` | Qué audita `py_audit.py` |
| `DS_SRC_ROOT` | `src` | Dónde corre `mypy` |
| `DS_IMMUTABLE_DIRS` | `data/raw,wiki/raw` | Qué protege `git_audit.py` contra escritura |

Lo que sí crea este sistema son sus propios resultados, porque no existían antes de usarlo:
`specs/` (la sombra ejecutable de cada issue), `experiments/` (auditorías y evaluaciones),
`evals/` (golden sets y el ledger), `wiki/` (lo que se aprende). Esos cuatro son contenido nuevo,
no estructura preexistente que este sistema pise.

## Qué vive dónde

```
CLAUDE.md                El contrato. Este documento.
setup-repo.py            Bootstrap de una vez: labels, branch protection en GitHub.
.claude/agents/*.md      Los 6 roles — subagentes de Claude Code.
.claude/commands/*.md    Los 5 comandos humanos — slash commands.
.claude/skills/*/        Metodología que ds-manager invoca (define-tests/evals/metrics).
.claude/settings.json    El hook que hace cumplir "rojo antes que verde" de verdad.
gates/                   Comprobaciones ejecutables en Python puro — sin dependencia de Claude.
specs/, experiments/,
evals/, wiki/            Lo que se genera al usar el sistema.
```

No hay `sync.py` ni ninguna capa de generación. `.claude/` es la fuente, escrita directamente en
su formato final — nada que traducir, nada que regenerar cuando cambias un rol o un comando.

## GitHub es obligatorio, y son tres puntos, no dos

Todo trabajo empieza en un issue y termina en una PR. Tres puntos requieren una persona:

| Punto | Comando | Qué haces |
|---|---|---|
| **Crear** | `/create-issue` (o `/grill-me` si la idea está en bruto) | Apruebas la spec: criterios, tests/evals/métricas, alcance |
| **Implementar** | fin de `/implement-issue` | Ves la PR completa —diff, commits, evidencia, wiki— en local y confirmas antes de que toque GitHub |
| **Mergear** | revisas la PR ya en GitHub | Apruebas o pides cambios. Mergear ES aceptar el resultado |

`/implement-issue` corre sin pausas hasta armar la PR local — datos, implementación por criterio,
integración, **las únicas miradas a los recursos que solo se miran una vez**, compilación al
wiki. No te pide permiso a mitad de camino. Pero no toca GitHub hasta que confirmes la PR local.

## Seis roles, dos bucles de convergencia

```
ds-manager       interroga hasta converger, escribe el issue, metodología en revisión y arreglos
analyst          puerta de datos: fugas, techo de rendimiento, estrategia de split
ds-developer     implementa: rojo, luego verde, por criterio. Llama a wiki-generator al final
reviewer         corrección de código, no metodología. Solo lectura
validator        ejecuta test/eval/metric tras converger todo; dirige el arreglo; el único que
                 mira cualquier recurso de una sola mirada
wiki-generator   compila lo aprendido al wiki, una vez por issue, cuando todo ha convergido
```

La investigación de técnicas (SOTA, qué enfoque usa la literatura para un tipo de fuga) no es un
rol aparte: es una herramienta que `ds-manager` y `ds-developer` usan directamente.

```
grill-me:         explora el repo, pregunta una a una con recomendación propia,
                  siempre corre dentro de create-issue tras su discovery ligero
create-issue:     ds-manager escribe → analyst (puerta de datos, si hay metric) → issue
implement-issue:  por criterio: ds-developer ↔ {reviewer, ds-manager}, converge
                  → validator ejecuta integración contra dev, ↔ ds-developer si falla, converge
                  → únicas miradas (una por cada recurso: métrica, golden set de eval)
                  → ds-developer llama a wiki-generator, compila lo aprendido
                  → PR local → (tu confirmación) → PR en GitHub
```

Dos bucles de convergencia, un solo presupuesto de rondas por criterio: `gates/convergence.py`
cuenta las rondas de la revisión por criterio y las de la conversación de arreglo de
`validator` sobre el mismo contador — un arreglo que se mueve de un bucle a otro no reinicia el
tope (por defecto 3 rondas).

| Fase | Rol | Ocurre en |
|---|---|---|
| Discovery ligero, luego interrogatorio profundo con exploración | `ds-manager` (vía `/create-issue` → `/grill-me`) | Creación |
| Spec y clasificación test/eval/metric | `ds-manager` (vía `/create-issue`) | Creación |
| Auditoría de datos, techo de rendimiento | `analyst` | Ambos (si hace falta) |
| Rojo, luego verde, por criterio | `ds-developer` ↔ {`reviewer`, `ds-manager`} | Implementación, converge (tope 3 rondas) |
| Integración contra dev; arregla si falla | `validator` ↔ `ds-developer` (+ `reviewer`/`ds-manager` si toca código) | Implementación, converge (mismo tope, mismo contador) |
| Miradas a recursos de una sola mirada | `validator` vía `gates/holdout_ledger.py`, una llamada por recurso | Una vez cada uno |
| Compilar al wiki | `wiki-generator`, llamado por `ds-developer` | Una vez, al final |

Dos vueltas atrás. **DATA → SPEC**: si el techo de los datos está por debajo de un criterio,
`/create-issue` corrige el objetivo antes de crear el issue, o `/implement-issue` lo detecta si
los datos cambiaron después y **para y comenta en el issue**. **Cualquiera de los dos bucles de
convergencia sobre sí mismo**: al superar el tope de `gates/convergence.py`, se para y se reporta.

## TDD, EDD y Métricas

Cada criterio de aceptación se verifica de una de tres maneras, según **la naturaleza del
veredicto**:

| | Veredicto | Ejemplo |
|---|---|---|
| **test** | Binario, repetible | "rechaza una fila sin identificador" |
| **eval** | Binario, sobre salida de LLM | "la respuesta cita un documento recuperado" |
| **metric** | Distribución con umbral e IC | "AUC-PR ≥ 0.42, IC95 sobre el baseline" |

Regla: *misma entrada, misma salida → test; si no → eval o metric.* Una métrica de modelo nunca
es un `assert` en la suite: `gates/py_audit.py` lo hace fallar con `FRONT001`.

## Dos clases de recurso de una sola mirada

No solo la partición de test de una métrica de modelo. El `dev`/`test` de un golden set de
eval sigue la misma lógica: mirarlo repetidamente durante un arreglo lo convierte poco a poco en
un segundo conjunto de validación. Ambos se registran en el mismo `gates/holdout_ledger.py`, cada
uno bajo su propia ruta — cuenta las miradas por fichero, no comparten presupuesto entre sí, pero
cada uno se mira una sola vez.

## Reglas duras

- **Los directorios de `DS_IMMUTABLE_DIRS` son inmutables.** Los derivados se regeneran con script.
- **Nada se implementa sin spec aprobada.**
- **El rojo antes que el verde.** `gates/tdd_guard.py` lo comprueba; el commit `red` va antes
  que el `green` y va aunque falle.
- **Cada recurso de una sola mirada se mira una vez por issue**, cuando `validator` no tiene
  ninguna conversación de arreglo abierta, registrado en `gates/holdout_ledger.py`.
- **Toda métrica lleva intervalo de confianza** (bootstrap, n≥1000) o no se reporta.
- **Semillas fijadas y registradas.**
- **Un cambio por iteración.**
- **Toda métrica reportada registra el hash del commit** que la produjo.
- **El wiki se compila una vez por issue, al final, nunca a mitad de un bucle de arreglo.**

## Datos: DVC por defecto

Los ficheros grandes bajo `DS_IMMUTABLE_DIRS` (típicamente `data/raw/`) se versionan con DVC, no
con git: `dvc init` una vez, `dvc add data/raw` para cada fuente, `dvc remote add` para donde
vivan los datos de verdad (S3, GCS, un disco compartido — la elección es tuya, este contrato no
la presupone). El puntero (`data/raw.dvc`, pequeño) va a git; los datos van al remoto.

`dvc install --use-pre-commit-tool` genera los hooks de `.pre-commit-config.yaml` con la versión
correcta — el bloque que ya está ahí es de referencia, no lo edites a mano si puedes regenerarlo.
Esto es ortogonal a `gates/holdout_ledger.py`: DVC versiona el dataset entero; el ledger cuenta
miradas a un recurso concreto dentro de un issue concreto. Los dos hashean, por motivos distintos.

## Git

Rama por issue: `<n>-<slug>`, sin barra al principio — `gh issue develop` falla en algunas
versiones con barras en el nombre. Un commit por criterio, con prefijo y número de issue:
`red(#n-ACx):`, `green(#n-ACx):`. El historial demuestra la disciplina —
`gates/git_audit.py` lo comprueba. Nunca `git add -A`.

**Todo el trabajo es local hasta el Paso 10 de `/implement-issue`.** `setup-repo.py` lo convierte
en algo que GitHub bloquea técnicamente: la rama por defecto rechaza push directo desde cualquiera.

## Antes de mostrar cualquier PR local

```
python3 gates/check.py
```

Es lo mismo que ejecuta CI. `mypy` es opcional: se reporta pero no bloquea, por diseño — ver
`gates/check.py` si quieres cambiarlo. Nunca se relaja una comprobación bloqueante para ponerla
en verde.

## Calidad de código: Ruff

`ruff format` es compatible con la salida de Black; `ruff check` incluye las reglas equivalentes a
Flake8 y, con el conjunto `I`, las de isort. Un solo formateador con dos modos (format +
check).

## WIKI: Registro del aprendizaje realizado

`README.md` describe la herramienta: cómo instalar, qué comandos hay. Cambia poco. **Todo lo
demás va al wiki** — convención de GitHub Wiki, sin generación ni build: `wiki/raw/` (fuentes,
inmutable), `wiki/log.md`, y una jerarquía fija de seis páginas más `Home.md` y `_Sidebar.md`
(`templates/wiki/` trae la plantilla de cada una):

```
Home.md                                Puerta de entrada, índice de decisiones y fallos
_Sidebar.md                            Navegación lateral — debe enlazar a las seis
1.-Configuracion-y-Environment.md      Instalación, dependencias, Docker
2.-Ciclo-de-Vida-de-los-Datos.md       Fuentes, ETL, diccionario de datos
3.-Analisis-Exploratorio.md            Hallazgos del EDA, fugas investigadas, notebooks
4.-Modelado-y-Experimentos.md          Features, experimentos, tracking
5.-Evaluacion-y-Metricas.md            Resultado con IC, segmentación
6.-Produccion-y-Monitoreo.md           Despliegue, monitoreo, deriva
```

No se crean páginas nuevas. `decisiones/` y `fallos/` no tienen página propia: se registran como
subsecciones (`### 📌 Decisión: ...`, `### ⚠️ Modo de fallo: ...`) dentro de la página de la fase
donde ocurrieron, indexadas desde `Home.md` — así se conserva el **por qué**, que es lo que antes
hacía valiosas a esas dos carpetas, sin salirse de la jerarquía fija. `gates/wiki_lint.py`
comprueba que no falte ninguna de las seis, que `_Sidebar.md` las enlace todas, enlaces rotos y
contradicciones sin resolver.

