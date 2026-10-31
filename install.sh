#!/bin/sh
# Instala PipeLine para el usuario actual, sin sudo. No sobrescribe nada sin preguntar.
# Uso: ./install.sh [--dry-run]
set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck source=scripts/common.sh
. "$REPO/scripts/common.sh"

TARGET="$REPO/.venv/bin/pipeline"
PLUGIN_CHANGED=0
UNITS_CHANGED=0
KEPT=0

# Copia un fichero. Devuelve 0 si lo cambió, o lo cambiaría en una simulación.
install_file() {
  source=$1
  destination=$2
  mode=$3
  if [ ! -L "$destination" ] && [ -f "$destination" ] && cmp -s "$source" "$destination"; then
    say "Sin cambios: $destination"
    return 1
  fi
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    say "Ya existe y es distinto: $destination"
    diff -u "$destination" "$source" || true
    if [ "$DRY_RUN" -eq 1 ]; then
      plan "preguntaría antes de sustituirlo"
      return 0
    fi
    if ! ask "¿Sustituirlo?"; then
      say "Se conserva: $destination"
      KEPT=1
      return 1
    fi
  elif [ "$DRY_RUN" -eq 1 ]; then
    plan "crearía $destination"
    return 0
  fi
  mkdir -p "$(dirname -- "$destination")"
  temporary=$(mktemp "$destination.XXXXXX")
  cp "$source" "$temporary"
  chmod "$mode" "$temporary"
  mv -f "$temporary" "$destination"
  say "Instalado: $destination"
  return 0
}

install_data_dir() {
  if [ -d "$DATA_DIR" ]; then
    say "Sin cambios: $DATA_DIR"
  elif [ "$DRY_RUN" -eq 1 ]; then
    plan "crearía $DATA_DIR con permisos 700"
  else
    mkdir -p "$(dirname -- "$DATA_DIR")"
    mkdir -m 700 "$DATA_DIR"
    say "Creado: $DATA_DIR"
  fi
}

install_launcher() {
  # La ruta se escribe sin comillas en el lanzador: solo se admiten caracteres seguros.
  case "$TARGET" in
    *[!A-Za-z0-9._/-]*) die "la ruta del repositorio tiene caracteres no admitidos: $TARGET" ;;
  esac
  generated=$(mktemp)
  write_launcher "$TARGET" "$generated"
  if install_file "$generated" "$LAUNCHER" 755; then :; fi
  rm -f "$generated"
}

install_plugin() {
  for file in $PLUGIN_FILES; do
    if install_file "$REPO/plugin/$file" "$PLUGIN_DIR/$file" 644; then
      PLUGIN_CHANGED=1
    fi
  done
  if [ "$DRY_RUN" -eq 0 ] && has_command omarchy; then
    omarchy plugin validate "$PLUGIN_DIR" || say "Aviso: omarchy plugin validate ha fallado."
  fi
}

install_units() {
  for file in $UNIT_FILES; do
    if install_file "$REPO/systemd/$file" "$UNIT_DIR/$file" 644; then
      UNITS_CHANGED=1
    fi
  done
  if ! has_command systemctl; then
    say "Aviso: no se encuentra systemctl; el timer no se puede activar."
    return
  fi
  if [ "$UNITS_CHANGED" -eq 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      plan "ejecutaría systemctl --user daemon-reload"
    else
      systemctl --user daemon-reload
    fi
  fi
  if systemctl --user is-enabled pipeline-fetch.timer > /dev/null 2>&1; then
    say "El timer ya está habilitado."
  elif [ "$DRY_RUN" -eq 1 ]; then
    plan "preguntaría si habilitar el timer"
  elif ask "¿Habilitar el timer? Hará hasta 288 llamadas al día a CoinGecko"; then
    systemctl --user enable --now pipeline-fetch.timer
  else
    say "Timer sin habilitar. Para hacerlo: systemctl --user enable --now pipeline-fetch.timer"
  fi
}

# No usa `omarchy plugin enable`: ese comando reescribe shell.json sin copia ni diff.
offer_bar_entry() {
  if [ ! -f "$SHELL_JSON" ]; then
    say "No hay $SHELL_JSON: añadí {\"id\": \"$PLUGIN_ID\"} a bar.layout cuando lo tengas."
  elif ! has_command jq; then
    say "No se encuentra jq: añadí {\"id\": \"$PLUGIN_ID\"} a bar.layout.right en shell.json."
  elif ! jq -e . "$SHELL_JSON" > /dev/null 2>&1; then
    say "Aviso: shell.json no es JSON válido; no se ha tocado."
  elif shell_json_has_plugin; then
    say "La barra ya incluye $PLUGIN_ID."
  else
    edit_shell_json "¿Añadir $PLUGIN_ID a la barra con este cambio?" \
      '.bar.layout.right = ((.bar.layout.right // []) + [{"id": $id}])' || true
  fi
}

parse_args "$@"
require_user

if [ ! -x "$TARGET" ]; then
  say "Falta el entorno virtual. Crealo con:"
  say "  python3 -m venv .venv && .venv/bin/pip install ."
  die "no existe $TARGET"
fi
if [ -n "${XDG_DATA_HOME:-}" ] && [ "$XDG_DATA_HOME" != "$HOME/.local/share" ]; then
  say "Aviso: XDG_DATA_HOME apunta a otro sitio, pero el servicio solo puede escribir en $DATA_DIR."
fi

install_data_dir
install_launcher
install_plugin
install_units
offer_bar_entry

say ""
if [ "$KEPT" -eq 1 ]; then
  say "Algunos ficheros existentes se han conservado sin cambios."
fi
if [ "$DRY_RUN" -eq 1 ]; then
  say "Simulación terminada: no se ha cambiado nada."
elif [ "$PLUGIN_CHANGED" -eq 1 ]; then
  say "Reiniciá el shell para cargar el plugin: omarchy restart shell"
else
  say "Instalación terminada."
fi
say "Configuración opcional: copiá config.example.toml a ~/.config/pipeline/config.toml."
say "Nota: durante un modo de portal de una VPN, una pasada del timer puede salir fuera del túnel."
