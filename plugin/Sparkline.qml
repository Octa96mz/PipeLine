import QtQuick
import "Model.js" as Model

// Minigráfico. Va en un color neutro a propósito: el verde y el rojo solo indican la variación
// de la pastilla, que cubre otro período, y así no parecen contradecirse.
Canvas {
  id: root

  property var values: []
  property color lineColor: "white"

  onValuesChanged: requestPaint()
  onLineColorChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()

  onPaint: {
    var context = getContext("2d")
    context.reset()
    var points = Model.sparklinePoints(values, width, height, 1.5)
    if (points.length === 0) return
    context.strokeStyle = lineColor
    context.lineWidth = 1.25
    context.lineJoin = "round"
    context.beginPath()
    context.moveTo(points[0].x, points[0].y)
    for (var i = 1; i < points.length; i++) context.lineTo(points[i].x, points[i].y)
    context.stroke()
  }
}
