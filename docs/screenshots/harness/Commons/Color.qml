pragma Singleton
import QtQuick

QtObject {
  readonly property QtObject popups: QtObject {
    readonly property color background: "#1e2126"
    readonly property color text: "#e4e6e8"
    readonly property color border: "#565c64"
  }
}
