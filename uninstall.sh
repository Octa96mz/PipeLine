#!/bin/sh
# Desinstala PipeLine. Pregunta antes de borrar datos, configuración o lo que no reconozca.
# Uso: ./uninstall.sh [--dry-run]
set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck source=scripts/common.sh
. "$REPO/scripts/common.sh"

PLUGIN_REMOVED=0
UNITS_PRESENT=0

# Borra un fichero. Si no coincide con lo que instalaría este repositorio, pregunta antes.
remove_file() {
  expected=$1
  path=$2
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    return 0
  fi
  if [ -L "$path" ] || ! cmp -s "$expected" "$path"; then
    say "No coincide con lo que se instaló: $path"
    if [ "$DRY_RUN" -eq 1 ]; then
      plan "preguntaría antes de borrarlo"
      return 0
    fi
    if ! ask "¿Borrarlo igualmente?"; then
      say "Se conserva: $path"
      return 0
    fi
  elif [ "$DRY_RUN" -eq 1 ]; then
    plan "borraría $path"
    return 0
  fi
  rm -f -- "$path"
  say "Borrado: $path"
}

# Datos y configuración nunca se borran sin una respuesta afirmativa.
offer_directory_removal() {
  directory=$1
  question=$2
  if [ -L "$directory" ]; then
    say "Es un enlace simbólico, no se toca: $directory"
  elif [ ! -d "$directory" ]; then
    return 0
  elif [ "$DRY_RUN" -eq 1 ]; then
    plan "preguntaría antes de borrar $directory"
  elif ask "$question"; then
    rm -rf -- "$directory"
    say "Borrado: $directory"
  else
    say "Se conserva: $directory"
  fi
}

stop_timer() {
  for file in $UNIT_FILES; do
    if [ -e "$UNIT_DIR/$file" ]; then UNITS_PRESENT=1; fi
  done
  [ "$UNITS_PRESENT" -eq 1 ] || return 0
  has_command systemctl || return 0
  if [ "$DRY_RUN" -eq 1 ]; then
    plan "ejecutaría systemctl --user disable --now pipeline-fetch.timer"
    plan "ejecutaría systemctl --user stop pipeline-fetch.service"
  else
    systemctl --user disable --now pipeline-fetch.timer || true
    systemctl --user stop pipeline-fetch.service || true
  fi
}

remove_units() {
  [ "$UNITS_PRESENT" -eq 1 ] || return 0
  for file in $UNIT_FILES; do
    remove_file "$REPO/systemd/$file" "$UNIT_DIR/$file"
  done
  if has_command systemctl; then
    if [ "$DRY_RUN" -eq 1 ]; then
      plan "ejecutaría systemctl --user daemon-reload"
    else
      systemctl --user daemon-reload
    fi
  fi
}

remove_bar_entry() {
  [ -f "$SHELL_JSON" ] || return 0
  if ! has_command jq; then
    say "No se encuentra jq: quitá $PLUGIN_ID de shell.json a mano."
  elif ! jq -e . "$SHELL_JSON" > /dev/null 2>&1; then
    say "Aviso: shell.json no es JSON válido; no se ha tocado."
  elif shell_json_has_plugin; then
    edit_shell_json "¿Quitar $PLUGIN_ID de la barra con este cambio?" \
      '.bar.layout |= map_values(if type == "array" then map(select(.id? != $id)) else . end)' || true
  fi
}

remove_plugin() {
  [ -d "$PLUGIN_DIR" ] || return 0
  for file in $PLUGIN_FILES; do
    if [ -e "$PLUGIN_DIR/$file" ]; then
      PLUGIN_REMOVED=1
      remove_file "$REPO/plugin/$file" "$PLUGIN_DIR/$file"
    fi
  done
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  if rmdir "$PLUGIN_DIR" 2> /dev/null; then
    say "Borrado: $PLUGIN_DIR"
  else
    say "Se conserva porque aún contiene ficheros: $PLUGIN_DIR"
  fi
}

remove_launcher() {
  expected=$(mktemp)
  write_launcher "$REPO/.venv/bin/pipeline" "$expected"
  remove_file "$expected" "$LAUNCHER"
  rm -f "$expected"
}

parse_args "$@"
require_user

stop_timer
remove_units
remove_bar_entry
remove_plugin
remove_launcher
offer_directory_removal "$DATA_DIR" "¿Borrar los datos guardados en $DATA_DIR?"
offer_directory_removal "$HOME/.config/pipeline" \
  "¿Borrar la configuración y las claves de $HOME/.config/pipeline?"

say ""
if [ "$DRY_RUN" -eq 1 ]; then
  say "Simulación terminada: no se ha cambiado nada."
elif [ "$PLUGIN_REMOVED" -eq 1 ]; then
  say "Reiniciá el shell para descargar el plugin: omarchy restart shell"
else
  say "Desinstalación terminada."
fi
