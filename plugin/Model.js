// Lógica de la barra, sin dependencias de QML para poder probarla aparte.

var SCHEMA_VERSION = 1

function isUsable(report) {
  if (!report.bar || !Array.isArray(report.bar.items)) return false
  if (!Array.isArray(report.providers) || !Array.isArray(report.groups)) return false
  return report.groups.every(function(group) { return group && Array.isArray(group.items) })
}

// Interpreta la salida de `pipeline json`. Si no sirve, conserva el último informe
// válido: la barra sigue mostrando esos datos, marcados como obsoletos.
function parseReport(text, previous) {
  var report = null
  try {
    report = JSON.parse(text)
  } catch (error) {
    return { report: previous, failed: true, message: "pipeline no devolvió datos válidos" }
  }
  if (!report || report.schema_version !== SCHEMA_VERSION)
    return { report: previous, failed: true, message: "versión de datos no admitida" }
  if (report.status === "error")
    return { report: previous, failed: true, message: String(report.error || "error desconocido") }
  // Misma versión pero sin la estructura esperada: sin esto, el panel fallaría al recorrerla.
  if (!isUsable(report))
    return { report: previous, failed: true, message: "datos incompletos" }
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

// ---- Panel ----

function rowStateText(row, failed) {
  if (row.price === null) return row.state_label
  var age = row.age_text
  if (row.state === "held") return "retenido · " + age
  if (failed || row.state === "stale") return "obsoleto · " + age
  return age
}

function panelRow(row, failed) {
  return {
    symbol: row.symbol,
    name: row.name,
    priceText: row.price_text || "—",
    changeText: row.change_text || "—",
    role: colorRole(row.state, row.direction, failed),
    stateText: rowStateText(row, failed),
    // Solo la retención se explica en su fila: el resto de motivos va en el aviso superior.
    note: row.state === "held" ? row.reason : "",
    series: row.series
  }
}

function panelGroups(result) {
  if (!result || !result.report || !result.report.groups) return []
  return result.report.groups.map(function(group) {
    var unavailable = group.items.length > 0 && group.items.every(function(row) {
      return row.state === "unavailable"
    })
    return {
      title: group.title,
      seriesLabel: group.series_label || "",
      changeLabel: group.change_label || "",
      // Un grupo entero sin proveedor ocupa una línea en vez de una fila por símbolo.
      summary: unavailable
        ? group.items.map(function(row) { return row.name }).join(", ") + " · " + group.items[0].reason.toLowerCase()
        : "",
      rows: unavailable ? [] : group.items.map(function(row) { return panelRow(row, result.failed) })
    }
  })
}

function banner(result) {
  if (!result) return "Cargando…"
  if (result.failed) return "No se pudo actualizar: " + result.message
  var report = result.report
  if (!report) return ""
  if (report.status === "no_data") return "Todavía no hay datos."
  if (report.status !== "stale") return ""
  var reasons = []
  report.groups.forEach(function(group) {
    group.items.forEach(function(row) {
      if (row.state === "stale" && reasons.indexOf(row.reason) === -1) reasons.push(row.reason)
    })
  })
  return reasons.length > 0 ? "Datos obsoletos: " + reasons.join("; ") : ""
}

function footerLines(result) {
  if (!result || !result.report || !result.report.providers) return []
  var lines = []
  result.report.providers.forEach(function(provider) {
    var line = provider.attribution + " · llamadas (24 h): " + provider.calls_24h
    if (provider.last_attempt)
      line += " · último intento " + provider.last_attempt.age_text + ", " + provider.last_attempt.outcome_label
    lines.push(line)
    if (provider.cooldown_until_text)
      lines.push("En pausa por el proveedor hasta las " + provider.cooldown_until_text)
    if (provider.offline_streak >= 2)
      lines.push("Sin conexión en " + provider.offline_streak + " pasadas seguidas; próximo intento hacia las " + provider.next_attempt_text)
  })
  return lines
}

// `phase`: idle, requested (colector arrancado) o failed (systemctl falló).
function refreshState(result, phase) {
  if (phase === "requested")
    return { enabled: false, label: "Solicitado", note: "El colector solo llama a la API si ya le toca." }
  var providers = result && result.report && result.report.providers ? result.report.providers : []
  for (var i = 0; i < providers.length; i++) {
    // Durante una pausa el colector no llamaría: el botón lo dice en vez de aparentar que actúa.
    if (providers[i].cooldown_until_text)
      return { enabled: false, label: "En pausa hasta las " + providers[i].cooldown_until_text, note: "" }
  }
  if (phase === "failed")
    return { enabled: true, label: "Actualizar", note: "No se pudo iniciar el colector. ¿Está instalado el timer?" }
  return { enabled: true, label: "Actualizar", note: "" }
}

// Puntos de la línea del minigráfico, ajustados al área de dibujo.
function sparklinePoints(values, width, height, margin) {
  if (!values || values.length < 2 || width <= 0 || height <= 0) return []
  var low = Math.min.apply(null, values)
  var high = Math.max.apply(null, values)
  var usable = Math.max(0, height - 2 * margin)
  var step = (width - 2 * margin) / (values.length - 1)
  return values.map(function(value, index) {
    var ratio = high === low ? 0.5 : (value - low) / (high - low)
    return { x: margin + index * step, y: margin + usable * (1 - ratio) }
  })
}
