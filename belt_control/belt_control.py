"""
Belt cart keyboard control - Mac side.
Hold LEFT / RIGHT arrow -> move the cart
UP / DOWN arrow         -> increase / decrease speed
SPACE                   -> stop
ESC or close window     -> quit (cart stops)
"""
import glob
import sys
import time

import pygame
import serial

BAUD = 115200
SPEED_START = 400
SPEED_STEP = 200
SPEED_MIN, SPEED_MAX = 100, 4000
SEND_INTERVAL = 0.05


def find_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    ports = (glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*")
             + glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("No Arduino found. Plug it in, close the Arduino Serial Monitor, "
                 "or pass the port: python3 belt_control.py /dev/cu.XXXX")
    return ports[0]


def send(ser, text):
    ser.write((text + "\n").encode())


def main():
    port = find_port()
    ser = serial.Serial(port, BAUD, timeout=0)
    print(f"Connected to {port}. Waiting for the Arduino to reset...")
    time.sleep(2)
    ser.reset_input_buffer()

    pygame.init()
    screen = pygame.display.set_mode((480, 240))
    pygame.display.set_caption("Belt Control")
    font = pygame.font.SysFont("Menlo", 20)
    small = pygame.font.SysFont("Menlo", 15)
    clock = pygame.time.Clock()

    speed = SPEED_START
    send(ser, f"V{speed}")
    position = 0
    rx = b""
    last_send = 0.0
    running = True

    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_UP:
                        speed = min(SPEED_MAX, speed + SPEED_STEP)
                        send(ser, f"V{speed}")
                    elif event.key == pygame.K_DOWN:
                        speed = max(SPEED_MIN, speed - SPEED_STEP)
                        send(ser, f"V{speed}")

            keys = pygame.key.get_pressed()
            left, right = keys[pygame.K_LEFT], keys[pygame.K_RIGHT]
            if keys[pygame.K_SPACE] or left == right:
                direction = "S"
            else:
                direction = "L" if left else "R"

            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                send(ser, direction)
                last_send = now

            rx += ser.read(256)
            while b"\n" in rx:
                line, rx = rx.split(b"\n", 1)
                line = line.strip()
                if line.startswith(b"P"):
                    try:
                        position = int(line[1:])
                    except ValueError:
                        pass

            labels = {"L": "<< LEFT", "R": "RIGHT >>", "S": "stopped"}
            screen.fill((25, 25, 30))
            screen.blit(font.render(f"Direction: {labels[direction]}", True, (230, 230, 230)), (20, 20))
            screen.blit(font.render(f"Speed:     {speed} steps/s", True, (230, 230, 230)), (20, 55))
            screen.blit(font.render(f"Position:  {position} steps", True, (230, 230, 230)), (20, 90))
            help_lines = ["Hold <- / -> to move", "Up / Down: speed   Space: stop", "Esc: quit"]
            for i, h in enumerate(help_lines):
                screen.blit(small.render(h, True, (150, 150, 160)), (20, 145 + i * 24))
            pygame.display.flip()
            clock.tick(60)
    finally:
        send(ser, "S")
        time.sleep(0.1)
        ser.close()
        pygame.quit()


if __name__ == "__main__":
    main()
