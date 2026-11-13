#!/usr/bin/env bash
# Conecta scripts/claude-cuentas.sh a bash y zsh. Se puede correr varias veces sin duplicar nada.
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/claude-cuentas.sh"
LINEA="[ -f \"$SCRIPT\" ] && . \"$SCRIPT\"  # claude-cuentas"

mkdir -p /workspaces/.claude-cuentas/claude{1,2,3}
chmod 700 /workspaces/.claude-cuentas /workspaces/.claude-cuentas/claude{1,2,3}

for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  touch "$rc"
  grep -q "# claude-cuentas" "$rc" || echo "$LINEA" >> "$rc"
done

echo "Listo. Abre una terminal nueva (o corre: source ~/.bashrc) y usa claude1, claude2, claude3."
