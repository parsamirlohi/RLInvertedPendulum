# LED Controller
#   Up arrow    = brighter
#   Down arrow  = dimmer
#   Right arrow = blink faster
#   Left arrow  = blink slower
#   Space bar   = on/off
#   q           = quit

import curses
import glob
import time

import serial


def find_port():
    ports = glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*")
    if not ports:
        raise SystemExit("Couldn't find the Nano. Is it plugged in?")
    return ports[0]


KEY_TO_COMMAND = {
    curses.KEY_UP: b"+",
    curses.KEY_DOWN: b"-",
    curses.KEY_RIGHT: b"f",
    curses.KEY_LEFT: b"s",
    ord(" "): b"o",
}


def main(screen, port):
    arduino = serial.Serial(port, 9600, timeout=0)
    screen.addstr(0, 0, "Connecting to the Nano...")
    screen.refresh()
    time.sleep(2)

    curses.curs_set(0)
    screen.nodelay(True)
    screen.keypad(True)
    screen.clear()
    screen.addstr(0, 0, "LED Controller  (connected to " + port + ")")
    screen.addstr(2, 0, "  Up / Down     = brighter / dimmer")
    screen.addstr(3, 0, "  Right / Left  = faster / slower")
    screen.addstr(4, 0, "  Space         = on / off")
    screen.addstr(5, 0, "  q             = quit")
    screen.refresh()

    buffer = ""
    while True:
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            break
        if key in KEY_TO_COMMAND:
            arduino.write(KEY_TO_COMMAND[key])

        waiting = arduino.in_waiting
        if waiting:
            buffer += arduino.read(waiting).decode(errors="ignore")
            if "\n" in buffer:
                lines = buffer.split("\n")
                buffer = lines[-1]
                latest = lines[-2].strip()
                screen.move(7, 0)
                screen.clrtoeol()
                screen.addstr(7, 0, "Arduino: " + latest)
                screen.refresh()

        time.sleep(0.01)

    arduino.close()


if __name__ == "__main__":
    port = find_port()
    curses.wrapper(main, port)
