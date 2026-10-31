import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// Panel desplegable. Solo muestra lo que recibe: no lee ni descarga nada por su cuenta.
KeyboardPanel {
  id: panel

  property var result: null
  property string refreshPhase: "idle"
  property color colorUp: "#9ece6a"
  property color colorDown: "#f7768e"
  property color colorHeld: "#e0af68"

  signal closeRequested()
  signal switchRequested(int direction)
  signal refreshRequested()

  readonly property color textColor: Commons.Color.popups.text
  readonly property var groups: Model.panelGroups(result)
  readonly property string bannerText: Model.banner(result)
  readonly property var footer: Model.footerLines(result)
  readonly property var refresh: Model.refreshState(result, refreshPhase)

  // Anchos fijos de columna, para que las cifras queden alineadas entre grupos.
  readonly property int sparkWidth: Style.space(92)
  readonly property int priceWidth: Style.space(104)
  readonly property int pillWidth: Style.space(72)
  readonly property int gapWidth: Style.space(10)

  function pillColor(role) {
    if (role === "up") return colorUp
    if (role === "down") return colorDown
    if (role === "held") return colorHeld
    return "transparent"
  }

  focusTarget: keyCatcher
  contentWidth: panel.fittedContentWidth(Style.space(540))
  contentHeight: panel.fittedContentHeight(body.implicitHeight)

  PanelKeyCatcher {
    id: keyCatcher
    anchors.fill: parent
    onCloseRequested: panel.closeRequested()
    onTabRequested: function(direction) { panel.switchRequested(direction) }
    onMoveRequested: function(dx, dy) {
      var limit = Math.max(0, scroller.contentHeight - scroller.height)
      scroller.contentY = Math.max(0, Math.min(limit, scroller.contentY + dy * Style.space(40)))
    }

    Flickable {
      id: scroller
      anchors.fill: parent
      contentWidth: width
      contentHeight: body.implicitHeight
      clip: true
      interactive: contentHeight > height
      boundsBehavior: Flickable.StopAtBounds

      Column {
        id: body
        width: scroller.width
        spacing: Style.space(10)

        Row {
          width: parent.width
          spacing: panel.gapWidth

          Text {
            width: parent.width - refreshButton.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            text: "Mercados"
            color: panel.textColor
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Rectangle {
            id: refreshButton
            width: refreshLabel.implicitWidth + Style.space(16)
            height: refreshLabel.implicitHeight + Style.space(8)
            radius: Style.cornerRadius
            color: "transparent"
            border.width: 1
            border.color: Qt.alpha(panel.textColor, refreshArea.containsMouse && panel.refresh.enabled ? 0.8 : 0.35)
            opacity: panel.refresh.enabled ? 1 : 0.55

            Text {
              id: refreshLabel
              anchors.centerIn: parent
              text: panel.refresh.label
              color: panel.textColor
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }

            MouseArea {
              id: refreshArea
              anchors.fill: parent
              hoverEnabled: true
              enabled: panel.refresh.enabled
              cursorShape: Qt.PointingHandCursor
              onClicked: panel.refreshRequested()
            }
          }
        }

        Text {
          visible: panel.refresh.note !== ""
          width: parent.width
          text: panel.refresh.note
          color: panel.textColor
          opacity: 0.7
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          visible: panel.bannerText !== ""
          width: parent.width
          text: panel.bannerText
          color: panel.colorHeld
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: panel.groups

          Column {
            required property var modelData
            readonly property var group: modelData
            width: body.width
            spacing: Style.space(6)

            Row {
              width: parent.width
              spacing: panel.gapWidth

              Text {
                width: parent.width - panel.sparkWidth - panel.priceWidth - panel.pillWidth - 3 * parent.spacing
                text: group.title
                color: panel.textColor
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
              }

              // El período va una vez por grupo: en cada fila solo sería ruido.
              Text {
                width: panel.sparkWidth
                text: group.seriesLabel
                horizontalAlignment: Text.AlignHCenter
                color: panel.textColor
                opacity: 0.6
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }

              Item { width: panel.priceWidth; height: 1 }

              Text {
                width: panel.pillWidth
                text: group.changeLabel
                horizontalAlignment: Text.AlignHCenter
                color: panel.textColor
                opacity: 0.6
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }

            Text {
              visible: group.summary !== ""
              width: parent.width
              text: group.summary
              color: panel.textColor
              opacity: 0.55
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Repeater {
              model: group.rows

              Column {
                required property var modelData
                readonly property var row: modelData
                readonly property bool dimmed: row.role === "stale" || row.role === "none"
                width: body.width
                spacing: Style.space(2)

                Row {
                  width: parent.width
                  spacing: panel.gapWidth

                  Column {
                    width: parent.width - panel.sparkWidth - panel.priceWidth - panel.pillWidth - 3 * parent.spacing
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      width: parent.width
                      text: row.name
                      elide: Text.ElideRight
                      color: panel.textColor
                      font.family: Style.font.family
                      font.pixelSize: Style.font.body
                    }

                    // La antigüedad siempre es visible, también en un dato correcto.
                    Text {
                      width: parent.width
                      text: row.symbol + " · " + row.stateText
                      elide: Text.ElideRight
                      color: panel.textColor
                      opacity: 0.6
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Sparkline {
                    width: panel.sparkWidth
                    height: Style.space(26)
                    anchors.verticalCenter: parent.verticalCenter
                    values: row.series
                    lineColor: panel.textColor
                    opacity: dimmed ? 0.4 : 0.85
                  }

                  Text {
                    width: panel.priceWidth
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.priceText
                    horizontalAlignment: Text.AlignRight
                    color: panel.textColor
                    opacity: dimmed ? 0.55 : 1
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                  }

                  Rectangle {
                    width: panel.pillWidth
                    height: pillText.implicitHeight + Style.space(6)
                    anchors.verticalCenter: parent.verticalCenter
                    radius: height / 2
                    color: panel.pillColor(row.role)
                    border.width: dimmed ? 1 : 0
                    border.color: Qt.alpha(panel.textColor, 0.3)

                    Text {
                      id: pillText
                      anchors.centerIn: parent
                      text: row.changeText
                      color: dimmed ? panel.textColor : Commons.Color.popups.background
                      opacity: dimmed ? 0.55 : 1
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                    }
                  }
                }

                Text {
                  visible: row.note !== ""
                  width: parent.width
                  text: row.note
                  color: panel.colorHeld
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }
            }
          }
        }

        Repeater {
          model: panel.footer

          Text {
            required property string modelData
            width: body.width
            text: modelData
            color: panel.textColor
            opacity: 0.6
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }
}
