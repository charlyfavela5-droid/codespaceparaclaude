# Cuentas de Claude Code: claude1, claude2, claude3
# Cada cuenta guarda su login en su propia carpeta (CLAUDE_CONFIG_DIR).
# La carpeta vive en /workspaces, que persiste aunque el Codespace se detenga o se reconstruya.
# Este archivo se carga desde ~/.bashrc y ~/.zshrc (lo instala scripts/instalar-cuentas.sh).

export CLAUDE_CUENTAS_DIR="${CLAUDE_CUENTAS_DIR:-/workspaces/.claude-cuentas}"

_claude_cuenta() {
  local n="$1"; shift
  local dir="$CLAUDE_CUENTAS_DIR/claude$n"
  mkdir -p "$dir" && chmod 700 "$dir"
  CLAUDE_CONFIG_DIR="$dir" command claude "$@"
}

claude1() { _claude_cuenta 1 "$@"; }
claude2() { _claude_cuenta 2 "$@"; }
claude3() { _claude_cuenta 3 "$@"; }

# Muestra qué cuentas ya tienen login guardado
claude-cuentas() {
  local n dir
  for n in 1 2 3; do
    dir="$CLAUDE_CUENTAS_DIR/claude$n"
    if [ -s "$dir/.credentials.json" ]; then
      echo "claude$n: con sesión ($dir)"
    else
      echo "claude$n: sin sesión -> corre 'claude$n' y haz /login"
    fi
  done
}
