// Lógica de la barra, sin dependencias de QML para poder probarla aparte.

var SCHEMA_VERSION = 1

// Interpreta la salida de `pipeline json`. Si no sirve, conserva el último informe
// válido: la barra sigue mostrando esos datos, marcados como obsoletos.
function parseReport(text, previous) {
  var report = null
  try {
    report = JSON.parse(text)
  } catch (error) {
    return { report: previous, failed: true, message: "no se pudo ejecutar pipeline" }
  }
  if (!report || report.schema_version !== SCHEMA_VERSION)
    return { report: previous, failed: true, message: "versión de datos no admitida" }
  if (report.status === "error")
    return { report: previous, failed: true, message: String(report.error || "error desconocido") }
  return { report: report, failed: false, message: "" }
}

function colorRole(state, direction, failed) {
  if (state === "unavailable" || state === "no_data") return "none"
  if (state === "held") return "held"
  if (failed || state === "stale") return "stale"
  if (direction === "up") return "up"
  if (direction === "down") return "down"
  return "flat"
}

function glyph(role) {
  if (role === "up") return "▲"
  if (role === "down") return "▼"
  if (role === "held") return "!"
  return ""
}

function barItems(result) {
  if (!result || !result.report || !result.report.bar) return []
  return result.report.bar.items.map(function(item) {
    var role = colorRole(item.state, item.direction, result.failed)
    return { label: item.label, value: item.value_text, glyph: glyph(role), role: role }
  })
}

function tooltip(result) {
  if (!result) return "PipeLine: cargando"
  var saved = result.report && result.report.bar ? result.report.bar.tooltip : ""
  if (!result.failed) return saved
  var problem = "No se pudo actualizar: " + result.message
  return saved ? problem + "\n" + saved : problem
}
