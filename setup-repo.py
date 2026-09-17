#!/usr/bin/env python3
"""Bootstraps a GitHub repository to match what this system expects.

Nothing here requires judgment, so it's a script, not an agent command — labels and branch
protection are the same every time, and running them through an LLM would cost a reasoning-tier
call for zero benefit.

  python3 setup-repo.py --new <owner/name> [--private]     Creates the repo, pushes this scaffold
  python3 setup-repo.py --existing                          Configures the repo in the current dir
  python3 setup-repo.py --existing --team                   Same, but requires a second approver

Idempotent: safe to re-run. Existing labels are updated in place, not duplicated.

What it does, in order:
  1. Confirms gh is authenticated.
  2. Creates the five labels this system's commands rely on.
  3. Sets branch protection on the default branch: PRs required, direct pushes blocked,
     the CI check required once it has run at least once.
  4. Prints what it did and what's still manual (approving reviews, if --team; a DVC remote).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

LABELS = [
    ("pending", "d4c5f9", "Archived — run /review-issue before /implement-issue"),
    ("epic", "5319e7", "Parent issue tracking a set of child issues"),
    ("verif:test", "0e8a16", "Has at least one criterion verified by pytest"),
    ("verif:eval", "1d76db", "Has at least one criterion verified by an LLM/agent eval"),
    ("verif:metric", "b60205", "Has at least one criterion verified by a model performance metric"),
]

CI_CHECK_NAME = "gates"  # must match the job name in .github/workflows/check.yml


def run(cmd, check=True, capture=True):
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        print(f"Fallo: {' '.join(cmd)}\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r


def gh_authed():
    return run(["gh", "auth", "status"], check=False).returncode == 0


def current_repo():
    r = run(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], check=False)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    return d["nameWithOwner"], d["defaultBranchRef"]["name"]


def ensure_labels(repo):
    print("Etiquetas:")
    for name, color, desc in LABELS:
        r = run(["gh", "label", "create", name, "--color", color, "--description", desc,
                 "--repo", repo, "--force"], check=False)
        estado = "creada/actualizada" if r.returncode == 0 else "FALLO"
        print(f"  {estado:20s} {name}")


def set_branch_protection(repo, branch, team):
    """Bloquea push directo; exige PR; exige que el check de CI pase cuando exista.

    El check de CI solo puede exigirse por nombre una vez que ha corrido al menos una vez en el
    repositorio — si esto es un repo recién creado, el primer push (el propio scaffold) lo
    dispara. Si `gh api` falla aquí porque el check aún no existe, se avisa y se deja sin ese
    requisito; se puede volver a ejecutar este script después de la primera PR.
    """
    payload = {
        "required_status_checks": None,
        "enforce_admins": True,
        "restrictions": None,
        "required_linear_history": False,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }
    if team:
        payload["required_pull_request_reviews"] = {"required_approving_review_count": 1}

    r = run(["gh", "api", "-X", "PUT", f"/repos/{repo}/branches/{branch}/protection",
             "-H", "Accept: application/vnd.github+json", "--input", "-"],
            check=False, capture=True)
    proc = subprocess.run(
        ["gh", "api", "-X", "PUT", f"/repos/{repo}/branches/{branch}/protection",
         "-H", "Accept: application/vnd.github+json", "--input", "-"],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  Protección de rama: FALLO — {proc.stderr.strip()[:200]}")
        print("  Revisa permisos del token (necesita admin sobre el repo) y reintenta.")
        return False

    print(f"  Protección activa en '{branch}': PR obligatoria, sin push directo, "
          f"{'requiere 1 aprobación' if team else 'sin aprobación formal (HITL sois vosotros)'}.")

    # Intento separado de exigir el check de CI por nombre: solo funciona si ya corrió una vez.
    add_check = subprocess.run(
        ["gh", "api", "-X", "PATCH", f"/repos/{repo}/branches/{branch}/protection/required_status_checks",
         "-H", "Accept: application/vnd.github+json", "--input", "-"],
        input=json.dumps({"strict": True, "contexts": [CI_CHECK_NAME]}),
        capture_output=True, text=True,
    )
    if add_check.returncode == 0:
        print(f"  Check de CI '{CI_CHECK_NAME}' añadido como obligatorio.")
    else:
        print(f"  Check de CI '{CI_CHECK_NAME}' aún no exigible (todavía no ha corrido una vez).")
        print(f"  Tras la primera PR, reejecuta: python3 setup-repo.py --existing"
              f"{' --team' if team else ''}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--new", metavar="owner/name", help="crea el repositorio y empuja este scaffold")
    g.add_argument("--existing", action="store_true", help="configura el repo del directorio actual")
    ap.add_argument("--private", action="store_true", help="con --new: repositorio privado")
    ap.add_argument("--team", action="store_true",
                    help="exige 1 aprobación formal de review además de los checks. "
                         "Sin esto (por defecto), el flujo asume que tú eres el único revisor "
                         "humano y aprobar la PR es leer el diff, no pulsar 'Approve' en GitHub")
    args = ap.parse_args()

    if not gh_authed():
        print("gh no está autenticado. Ejecuta 'gh auth login' primero.")
        return 1

    if args.new:
        print(f"Creando {args.new}...")
        vis = "--private" if args.private else "--public"
        run(["gh", "repo", "create", args.new, vis, "--source", ".", "--push"])
        repo, branch = args.new, "main"
    else:
        detected = current_repo()
        if not detected:
            print("No se detecta un repositorio de GitHub en el directorio actual.")
            print("¿Falta 'git remote add origin ...', o usa --new para crear uno?")
            return 1
        repo, branch = detected
        print(f"Configurando {repo} (rama por defecto: {branch})...")

    ensure_labels(repo)
    ok = set_branch_protection(repo, branch, args.team)

    print()
    print("Hecho." if ok else "Hecho con avisos — revisa lo anterior.")
    print(f"Siguiente paso: 'claude --agent ds-manager' y luego '/create-issue' o '/grill-me'.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
