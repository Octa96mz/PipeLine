import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import "plugin"
import "plugin/Model.js" as Model
import "data.js" as Data

// Dibuja el panel real con datos sintéticos y guarda solo ese elemento, sin capturar la pantalla.
ShellRoot {
  id: shell

  property var pending: ["panel", "panel-stale"]
  property string current: pending[0]

  FloatingWindow {
    implicitWidth: 560
    implicitHeight: 720
    color: "transparent"
    visible: true

    Column {
      id: capture

      MarketPanel {
        id: marketPanel
        result: Model.parseReport(shell.current === "panel" ? Data.normal : Data.degraded, null)
      }

      Rectangle {
        width: marketPanel.width
        height: note.implicitHeight + 16
        color: Commons.Color.popups.background

        Text {
          id: note
          anchors.centerIn: parent
          width: parent.width - 28
          text: "Datos sintéticos · reproducción con tema neutro, no es una captura del shell real"
          color: "#e0af68"
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }

  Timer {
    interval: 800
    running: true
    repeat: true
    onTriggered: {
      var name = shell.current
      var saved = capture.grabToImage(function(image) {
        console.log("saved", name, image.saveToFile(Data.outputDir + "/" + name + ".png"))
        var next = shell.pending.indexOf(name) + 1
        if (next >= shell.pending.length) Qt.quit()
        else shell.current = shell.pending[next]
      }, Qt.size(capture.width * 2, capture.height * 2))
      if (!saved) { console.log("GRAB_FAILED"); Qt.quit() }
    }
  }
}
