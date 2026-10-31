pragma Singleton
import QtQuick

// Sustituye a qs.Commons, que solo existe dentro del shell de Omarchy: es un tema neutro.
QtObject {
  readonly property int cornerRadius: 8
  readonly property QtObject font: QtObject {
    readonly property string family: "monospace"
    readonly property int caption: 10
    readonly property int bodySmall: 11
    readonly property int body: 12
    readonly property int title: 14
  }

  function space(pixels) { return pixels }
}
