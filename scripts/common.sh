# shellcheck shell=sh disable=SC2034
# Funciones compartidas por install.sh y uninstall.sh. Se carga con `.`, no se ejecuta.
# SC2034: las variables de aquí las usan los scripts que cargan este fichero.

PLUGIN_ID="pipeline.market"
PLUGIN_FILES="manifest.json Widget.qml Model.js MarketPanel.qml Sparkline.qml"
UNIT_FILES="pipeline-fetch.service pipeline-fetch.timer"

DRY_RUN=0
LAUNCHER="$HOME/.local/bin/pipeline"
DATA_DIR="$HOME/.local/share/pipeline"
UNIT_DIR="$HOME/.config/systemd/user"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
SHELL_JSON="$HOME/.config/omarchy/shell.json"

say() {
  printf '%s\n' "$*"
}

plan() {
  printf '[simulación] %s\n' "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

# La respuesta por defecto siempre es no. Sin entrada disponible, también.
ask() {
  printf '%s [s/N] ' "$1"
  answer=""
  IFS= read -r answer || answer=""
  case "$answer" in
    s | S | si | SI | Si | sí | Sí | SÍ) return 0 ;;
    *) return 1 ;;
  esac
}

parse_args() {
  for argument in "$@"; do
    case "$argument" in
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        say "Uso: $(basename "$0") [--dry-run]"
        exit 0
        ;;
      *) die "opción desconocida: $argument" ;;
    esac
  done
}

require_user() {
  [ -n "${HOME:-}" ] || die "HOME no está definido"
  # Todo se instala para el usuario: como root acabaría en el directorio de otra persona.
  [ "$(id -u)" -ne 0 ] || die "no lo ejecutes como root ni con sudo"
}

has_command() {
  command -v "$1" > /dev/null 2>&1
}

# Contenido exacto del lanzador. La ruta se calcula aquí: el repositorio no guarda rutas personales.
write_launcher() {
  printf '#!/bin/sh\nexec %s "$@"\n' "$1" > "$2"
}

shell_json_has_plugin() {
  jq -e --arg id "$PLUGIN_ID" \
    '[.bar.layout[]?[]? | select(.id? == $id)] | length > 0' "$SHELL_JSON" > /dev/null 2>&1
}

# Una copia nunca pisa a otra, aunque dos cambios caigan en el mismo segundo.
new_backup_path() {
  base="$SHELL_JSON.bak.$(date +%Y%m%d-%H%M%S)"
  candidate=$base
  number=1
  while [ -e "$candidate" ]; do
    candidate="$base.$number"
    number=$((number + 1))
  done
  printf '%s\n' "$candidate"
}

# Aplica un filtro de jq a shell.json con copia fechada, diff y confirmación explícita.
# La vista previa va a un temporal del sistema: junto a shell.json, el shell podría reaccionar.
edit_shell_json() {
  question=$1
  filter=$2
  original=$(mktemp)
  proposed=$(mktemp)
  cp "$SHELL_JSON" "$original"
  if ! jq --arg id "$PLUGIN_ID" "$filter" "$original" > "$proposed" || ! jq -e . "$proposed" > /dev/null; then
    rm -f "$original" "$proposed"
    say "No se pudo preparar el cambio de shell.json: no se ha tocado."
    return 1
  fi
  diff -u --label shell.json "$original" --label shell.json.propuesto "$proposed" || true
  if [ "$DRY_RUN" -eq 1 ]; then
    rm -f "$original" "$proposed"
    plan "preguntaría antes de aplicar este cambio a shell.json"
    return 1
  fi
  if ! ask "$question"; then
    rm -f "$original" "$proposed"
    say "shell.json no se ha tocado."
    return 1
  fi
  # La barra reescribe este fichero al arrastrar widgets: lo aprobado debe seguir siendo válido.
  if ! cmp -s "$original" "$SHELL_JSON"; then
    rm -f "$original" "$proposed"
    say "shell.json cambió mientras esperaba tu respuesta: no se ha tocado. Volvé a ejecutarlo."
    return 1
  fi
  backup=$(new_backup_path)
  cp -p "$SHELL_JSON" "$backup"
  replacement=$(mktemp "$SHELL_JSON.XXXXXX")
  cat "$proposed" > "$replacement"
  chmod "$(stat -c %a "$SHELL_JSON")" "$replacement"
  mv -f "$replacement" "$SHELL_JSON"
  rm -f "$original" "$proposed"
  say "shell.json actualizado. Copia: $backup"
  say "Para deshacerlo: cp -p '$backup' '$SHELL_JSON'"
}
