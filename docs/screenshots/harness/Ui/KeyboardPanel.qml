import QtQuick
import qs.Commons
import qs.Commons as Commons

// Sustituto sin ventana de la superficie del shell: solo dibuja la tarjeta del panel.
Rectangle {
  id: root

  property var anchorItem: null
  property var owner: null
  property var bar: null
  property bool open: true
  property Item focusTarget: null
  property int contentWidth: 0
  property int contentHeight: 0
  readonly property int cardPadding: 14

  default property alias contentItem: holder.children

  function fittedContentWidth(width) { return width }
  function fittedContentHeight(height) { return height + cardPadding * 2 }

  width: contentWidth
  height: contentHeight
  color: Commons.Color.popups.background
  border.color: Commons.Color.popups.border
  border.width: 1
  radius: Style.cornerRadius

  Item {
    id: holder
    anchors.fill: parent
    anchors.margins: root.cardPadding
  }
}
