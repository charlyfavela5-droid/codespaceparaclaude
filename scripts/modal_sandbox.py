"""Sandbox de Modal con Claude Code y las cuentas claude1, claude2, claude3.

Uso (desde la raíz del repo, con `modal setup` ya hecho):
    python scripts/modal_sandbox.py crear      # levanta el sandbox y te da su ID
    modal shell <sandbox-id>                   # entras y usas claude1 / claude2 / claude3
    python scripts/modal_sandbox.py lista      # sandboxes vivos
    python scripts/modal_sandbox.py apagar <sandbox-id>

Los logins de cada cuenta se guardan en el Volume de Modal "claude-cuentas"
(/cuentas/claudeN dentro del sandbox), así que sobreviven aunque apagues el sandbox.
El repo se copia a /repo sin .git ni archivos de credenciales.
"""

import sys
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent
APP_NAME = "claude-sandbox"
HORAS = 8  # tiempo máximo de vida del sandbox

imagen = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl", "git", "ca-certificates", "less", "procps")
    .run_commands(
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        "apt-get install -y nodejs",
        "npm install -g @anthropic-ai/claude-code",
        # Carga claude1/claude2/claude3 en cada shell
        "echo '[ -f /repo/scripts/claude-cuentas.sh ] && . /repo/scripts/claude-cuentas.sh' >> /root/.bashrc",
    )
    .env({"CLAUDE_CUENTAS_DIR": "/cuentas"})
    .add_local_dir(
        REPO,
        "/repo",
        ignore=[".git", "**/.credentials.json", ".claude/settings.local.json", ".claude-cuentas", "**/__pycache__"],
    )
)

cuentas = modal.Volume.from_name("claude-cuentas", create_if_missing=True)


def crear():
    app = modal.App.lookup(APP_NAME, create_if_missing=True)
    with modal.enable_output():
        sb = modal.Sandbox.create(
            "sleep", "infinity",
            app=app,
            image=imagen,
            volumes={"/cuentas": cuentas},
            workdir="/repo",
            timeout=HORAS * 3600,
        )
    sb.exec("bash", "-c", "mkdir -p /cuentas/claude1 /cuentas/claude2 /cuentas/claude3 && chmod 700 /cuentas/claude*").wait()
    print(f"\nSandbox listo: {sb.object_id}")
    print(f"Entra con:  modal shell {sb.object_id}")
    print("Adentro:    claude-cuentas   (ver logins)   |   claude1 / claude2 / claude3")


def lista():
    app = modal.App.lookup(APP_NAME, create_if_missing=True)
    for sb in modal.Sandbox.list(app_id=app.app_id):
        print(sb.object_id)


def apagar(sandbox_id: str):
    sb = modal.Sandbox.from_id(sandbox_id)
    sb.terminate()
    print(f"Apagado {sandbox_id}. Los logins quedan guardados en el Volume 'claude-cuentas'.")


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else "crear"
    if comando == "crear":
        crear()
    elif comando == "lista":
        lista()
    elif comando == "apagar" and len(sys.argv) > 2:
        apagar(sys.argv[2])
    else:
        print(__doc__)
