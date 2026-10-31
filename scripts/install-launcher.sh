#!/bin/sh
# Crea ~/.local/bin/pipeline, un exec hacia el venv de este repositorio.
# La ruta se calcula al ejecutarlo: el repositorio no guarda rutas personales.
# Nunca sobrescribe: si ya existe, lo indica y termina con error.
set -eu

repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
target="$repo/.venv/bin/pipeline"
launcher="$HOME/.local/bin/pipeline"

if [ ! -x "$target" ]; then
  echo "No existe el venv: $target" >&2
  exit 1
fi
# La ruta se escribe sin comillas en el lanzador: solo se admiten caracteres seguros.
case "$target" in
  *[!A-Za-z0-9._/-]*)
    echo "La ruta del repositorio tiene caracteres no admitidos: $target" >&2
    exit 1
    ;;
esac

mkdir -p "$HOME/.local/bin"
temporary=$(mktemp "$launcher.XXXXXX")
trap 'rm -f "$temporary"' EXIT
printf '#!/bin/sh\nexec %s "$@"\n' "$target" > "$temporary"
chmod 755 "$temporary"
# `ln` falla si el destino ya existe, sin el hueco de comprobar antes y escribir después.
if ! ln "$temporary" "$launcher" 2>/dev/null; then
  echo "Ya existe, no se toca: $launcher" >&2
  exit 1
fi
echo "Creado: $launcher"
