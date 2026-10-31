import QtQuick

Item {
  signal closeRequested()
  signal tabRequested(int direction)
  signal moveRequested(int dx, int dy)
}
