import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// Elemento compacto de la barra. Solo lee `pipeline json`: no accede a ninguna API.
BarWidget {
  id: root
  moduleName: "pipeline.market"

  // Paleta fija de verde y rojo, ya que el tema de Omarchy no define un verde.
  readonly property color colorUp: "#9ece6a"
  readonly property color colorDown: "#f7768e"
  readonly property color colorHeld: "#e0af68"
  readonly property color colorNeutral: bar ? bar.foreground : Commons.Color.foreground

  readonly property string command: setting("command", Quickshell.env("HOME") + "/.local/bin/pipeline")
  readonly property int refreshSeconds: Math.max(15, parseInt(setting("refreshSeconds", 60), 10) || 60)

  property var result: null
  property string refreshPhase: "idle"
  readonly property var items: Model.barItems(result)

  property bool panelOpen: false
  property bool popoutSwitchClosing: false
  property var registeredBar: null

  // Contrato que la barra espera de un widget con panel: open, close y opened.
  readonly property bool opened: panelOpen

  function open() { panelOpen = true; refresh() }
  function close() { panelOpen = false }

  // La barra llama a esto cuando se abre el panel de otro widget.
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { popoutSwitchClosing = false })
  }

  // Con un panel abierto, la barra reenvía aquí el clic para cambiar de panel de una vez.
  function triggerPress(button) {
    if (bar) bar.hideTooltip(root)
    if (button === Qt.LeftButton) panelOpen ? close() : open()
  }

  function syncClickRegistration() {
    if (registeredBar) registeredBar.unregisterClickTarget(root)
    registeredBar = bar
    if (registeredBar) registeredBar.registerClickTarget(root)
  }

  function refresh() {
    if (!reader.running) reader.running = true
  }

  // El botón solo arranca el servicio del colector, que decide si toca llamar a la API.
  function requestCollection() {
    if (!collector.running) collector.running = true
  }

  function roleColor(role) {
    if (role === "up") return colorUp
    if (role === "down") return colorDown
    if (role === "held") return colorHeld
    return colorNeutral
  }

  onBarChanged: syncClickRegistration()
  Component.onCompleted: syncClickRegistration()
  Component.onDestruction: if (registeredBar) registeredBar.unregisterClickTarget(root)

  implicitWidth: (vertical ? compactLabel.implicitWidth : content.implicitWidth) + Style.space(14)
  implicitHeight: barSize

  // Lectura asíncrona: `timeout` garantiza que termina aunque pipeline se quede colgado.
  Process {
    id: reader
    command: ["timeout", "-k", "1", "3", root.command, "json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.result = Model.parseReport(text, root.result ? root.result.report : null)
    }
  }

  Process {
    id: collector
    command: ["systemctl", "--user", "start", "--no-block", "pipeline-fetch.service"]
    onExited: function(exitCode) {
      root.refreshPhase = exitCode === 0 ? "requested" : "failed"
      if (exitCode === 0) afterCollection.restart()
    }
  }

  // Da tiempo a que termine el colector y vuelve a leer lo que haya guardado.
  Timer {
    id: afterCollection
    interval: 4000
    onTriggered: {
      root.refreshPhase = "idle"
      root.refresh()
    }
  }

  Timer {
    interval: root.refreshSeconds * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  // En una barra vertical no caben las cifras.
  Text {
    id: compactLabel
    visible: root.vertical
    anchors.centerIn: parent
    text: "PL"
    color: root.roleColor(root.items.length > 0 ? root.items[0].role : "none")
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Row {
    id: content
    visible: !root.vertical
    anchors.centerIn: parent
    spacing: Style.space(10)

    // Sin datos todavía, o sin poder ejecutar pipeline por primera vez.
    Text {
      visible: root.items.length === 0
      text: "PL —"
      color: root.colorNeutral
      opacity: 0.55
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Repeater {
      model: root.items

      Row {
        required property var modelData
        spacing: Style.space(4)

        Text {
          text: modelData.label
          color: root.colorNeutral
          opacity: 0.7
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Text {
          text: modelData.glyph ? modelData.value + " " + modelData.glyph : modelData.value
          color: root.roleColor(modelData.role)
          opacity: modelData.role === "stale" || modelData.role === "none" ? 0.55 : 1
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: if (root.bar) root.bar.showTooltip(root, Model.tooltip(root.result))
    onExited: if (root.bar) root.bar.hideTooltip(root)
    onClicked: function(mouse) { root.triggerPress(mouse.button) }
  }

  MarketPanel {
    anchorItem: root
    owner: root
    bar: root.bar
    open: root.panelOpen
    result: root.result
    refreshPhase: root.refreshPhase
    colorUp: root.colorUp
    colorDown: root.colorDown
    colorHeld: root.colorHeld
    onCloseRequested: root.close()
    onSwitchRequested: function(direction) { if (root.bar) root.bar.switchPanelFrom(root, direction) }
    onRefreshRequested: root.requestCollection()
  }
}
