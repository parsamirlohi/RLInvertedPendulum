#!/usr/bin/env python3
"""
Belt cart trajectory player - Mac side.

Reads an Excel (.xlsx) or CSV file with a time column and a position column,
then drives the belt cart to those positions at those times.

    python3 trajectory_player.py trajectories/example_trajectory.csv --dry-run
    python3 trajectory_player.py my_data.xlsx --units mm --steps-per-mm 80

Needs the updated belt_control.ino (G<pos> command) on the Arduino.
Close the Arduino Serial Monitor first. Ctrl+C stops the cart at any time.
"""
import argparse
import bisect
import csv
import glob
import sys
import time
from pathlib import Path

BAUD = 115200
FIRMWARE_SPEED_CAP = 4000.0   # steps/s, same as MAX_SPEED_CAP in belt_control.ino
FIRMWARE_ACCEL = 1500.0       # steps/s^2, same as ACCELERATION in belt_control.ino
ARRIVE_TOL = 5                # steps: "close enough" to a target

TIME_TO_S = {"s": 1.0, "ms": 1e-3, "min": 60.0}
POS_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


# ---------------------------------------------------------------- file loading
def to_float(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def read_rows(path, sheet):
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        if sheet and sheet not in wb.sheetnames:
            sys.exit(f"Sheet '{sheet}' not found. Sheets in this file: {wb.sheetnames}")
        ws = wb[sheet] if sheet else wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if ext in (".csv", ".tsv", ".txt"):
        text = path.read_text(encoding="utf-8-sig")
        if ext == ".tsv":
            delim = "\t"
        else:
            try:
                delim = csv.Sniffer().sniff(text[:2048], delimiters=",;\t").delimiter
            except csv.Error:
                delim = ","
        return [row for row in csv.reader(text.splitlines(), delimiter=delim)]
    if ext == ".xls":
        sys.exit("Old .xls files are not supported. In Excel: File > Save As > .xlsx (or .csv).")
    sys.exit(f"Unsupported file type '{ext}'. Use .xlsx or .csv.")


def pick_column(header, spec, keywords, exact, default_idx):
    if spec is not None:
        if spec.isdigit():
            return int(spec) - 1
        if header:
            names = [str(h).strip().lower() for h in header]
            if spec.strip().lower() in names:
                return names.index(spec.strip().lower())
            for i, n in enumerate(names):
                if spec.strip().lower() in n:
                    return i
        sys.exit(f"Column '{spec}' not found. Use a header name or a 1-based column number.")
    if header:
        names = [str(h).strip().lower() if h is not None else "" for h in header]
        for i, n in enumerate(names):
            if n in exact or any(k in n for k in keywords):
                return i
    return default_idx


def load_trajectory(args):
    path = Path(args.file).expanduser()
    if not path.exists():
        sys.exit(f"File not found: {path}")
    rows = [r for r in read_rows(path, args.sheet) if any(c not in (None, "") for c in r)]
    if not rows:
        sys.exit("The file is empty.")

    first = rows[0]
    has_header = any(c not in (None, "") and to_float(c) is None for c in first)
    header = first if has_header else None
    data = rows[1:] if has_header else rows

    ti = pick_column(header, args.time_col, ("time", "sec"), ("t", "ms"), 0)
    xi = pick_column(header, args.pos_col, ("pos", "loc", "dist", "disp"), ("x",), 1)
    if ti == xi:
        sys.exit("Time and position resolved to the same column. Use --time-col and --pos-col.")
    if header:
        print(f"Using columns: time = '{header[ti]}', position = '{header[xi]}'")
    else:
        print(f"No header row found: time = column {ti + 1}, position = column {xi + 1}")

    pts, skipped = [], 0
    for r in data:
        t = to_float(r[ti]) if ti < len(r) else None
        x = to_float(r[xi]) if xi < len(r) else None
        if t is None or x is None:
            skipped += 1
            continue
        pts.append((t, x))
    if skipped:
        print(f"Warning: skipped {skipped} row(s) with missing or non-numeric values.")
    if len(pts) < 2:
        sys.exit("Need at least 2 valid (time, position) rows.")
    if any(pts[i][0] > pts[i + 1][0] for i in range(len(pts) - 1)):
        print("Warning: times were not in order; sorted them.")
        pts.sort(key=lambda p: p[0])
    for a, b in zip(pts, pts[1:]):
        if a[0] == b[0]:
            sys.exit(f"Duplicate time value {a[0]} in the file. Each row needs a unique time.")

    t_scale = TIME_TO_S[args.time_units]
    if args.units == "steps":
        x_scale = 1.0
    else:
        if not args.steps_per_mm:
            sys.exit(f"--units {args.units} needs --steps-per-mm (steps the motor takes per mm of belt travel).")
        x_scale = POS_TO_MM[args.units] * args.steps_per_mm
    t0 = pts[0][0]
    return Trajectory([(p[0] - t0) * t_scale for p in pts], [p[1] * x_scale for p in pts], args.mode)


class Trajectory:
    def __init__(self, t, x, mode):
        self.t, self.x, self.mode = t, x, mode
        self.duration = t[-1]

    def at(self, tt):
        t, x = self.t, self.x
        if tt <= t[0]:
            return x[0]
        if tt >= t[-1]:
            return x[-1]
        i = bisect.bisect_right(t, tt) - 1
        if self.mode == "hold":
            return x[i]
        f = (tt - t[i]) / (t[i + 1] - t[i])
        return x[i] + f * (x[i + 1] - x[i])

    def stats(self):
        t, x = self.t, self.x
        speeds = [(x[i + 1] - x[i]) / (t[i + 1] - t[i]) for i in range(len(t) - 1)]
        accels = [abs(speeds[i + 1] - speeds[i]) / ((t[i + 2] - t[i]) / 2) for i in range(len(speeds) - 1)]
        return {
            "n": len(t),
            "duration": self.duration,
            "xmin": min(x), "xmax": max(x),
            "vmax": max(abs(v) for v in speeds),
            "amax": max(accels) if accels else 0.0,
            "jump": max(abs(x[i + 1] - x[i]) for i in range(len(x) - 1)),
        }


# ------------------------------------------------------------------ the serial link
def find_port():
    ports = (glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*")
             + glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("No Arduino found. Plug it in, close the Arduino Serial Monitor, "
                 "or pass the port: --port /dev/cu.XXXX")
    return ports[0]


class Link:
    def __init__(self, ser):
        self.ser, self.rx, self.pos = ser, b"", None

    def send(self, text):
        self.ser.write((text + "\n").encode())

    def poll(self):
        self.rx += self.ser.read(256)
        while b"\n" in self.rx:
            line, self.rx = self.rx.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"P"):
                try:
                    self.pos = int(line[1:])
                except ValueError:
                    pass
        return self.pos


# ----------------------------------------------------------------------- running
def report(traj, args, offset_note):
    s = traj.stats()
    print(f"\nTrajectory: {s['n']} points, {s['duration']:.2f} s, mode = {args.mode}")
    print(f"  position range in file: {s['xmin']:.0f} to {s['xmax']:.0f} steps "
          f"(span {s['xmax'] - s['xmin']:.0f})  [{offset_note}]")
    problems = []
    if args.mode == "linear":
        print(f"  peak speed: {s['vmax']:.0f} steps/s   (limit {args.max_speed:.0f})")
        print(f"  peak acceleration at waypoints: {s['amax']:.0f} steps/s^2   (cart limit {FIRMWARE_ACCEL:.0f})")
        if s["vmax"] > args.max_speed:
            problems.append(f"Trajectory needs {s['vmax']:.0f} steps/s but the limit is {args.max_speed:.0f}. "
                            "Slow the data down (stretch the times) or raise --max-speed (firmware cap is 4000).")
        if s["amax"] > FIRMWARE_ACCEL:
            print("  note: sharper turns than the cart can follow will be rounded off.")
        lag = s["vmax"] / (2 * FIRMWARE_ACCEL)
        print(f"  expected lag at peak speed: about {lag:.2f} s (use --lead {lag:.2f} to compensate)")
    else:
        print(f"  largest jump between waypoints: {s['jump']:.0f} steps (the cart moves at up to "
              f"{args.max_speed:.0f} steps/s, so it arrives early and waits)")
    return problems


def run(args, traj):
    import serial
    port = args.port or find_port()
    ser = serial.Serial(port, BAUD, timeout=0)
    print(f"\nConnected to {port}. Waiting for the Arduino to reset...")
    time.sleep(2)
    ser.reset_input_buffer()
    link = Link(ser)
    period = 1.0 / args.rate
    log = None
    if args.log:
        log = open(args.log, "w", newline="")
        logw = csv.writer(log)
        logw.writerow(["time_s", "target_steps", "actual_steps"])

    try:
        link.send(f"V{int(args.max_speed)}")
        deadline = time.monotonic() + 3
        while link.pos is None and time.monotonic() < deadline:
            link.poll()
            time.sleep(0.02)
        if link.pos is None:
            sys.exit("No position reports from the Arduino. Is the updated belt_control.ino uploaded?")
        start_pos = link.pos
        offset = 0.0 if args.absolute else start_pos - traj.x[0]
        lo, hi = min(traj.x) + offset, max(traj.x) + offset
        print(f"Cart is at {start_pos} steps. This run will move it between {lo:.0f} and {hi:.0f} steps.")
        if (args.min_steps is not None and lo < args.min_steps) or \
           (args.max_steps is not None and hi > args.max_steps):
            sys.exit(f"Refusing to run: that range leaves your limits "
                     f"[{args.min_steps}, {args.max_steps}] steps.")
        if not args.yes:
            input("Make sure the belt has room to travel that far and is clear. Press Enter to start (Ctrl+C to cancel)... ")

        def go_to(target, timeout, label):
            target = int(round(target))
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                link.send(f"G{target}")
                p = link.poll()
                print(f"\r{label}: at {p} -> {target}      ", end="", flush=True)
                if p is not None and abs(p - target) <= ARRIVE_TOL:
                    print()
                    return True
                time.sleep(period)
            print()
            return False

        if not go_to(traj.x[0] + offset, 30, "Moving to start"):
            sys.exit("Could not reach the start position within 30 s.")

        print("Running trajectory...")
        t0 = time.monotonic()
        next_tick = t0
        while True:
            t = time.monotonic() - t0
            target = int(round(traj.at(t + args.lead) + offset))
            link.send(f"G{target}")
            actual = link.poll()
            if log:
                logw.writerow([f"{t:.3f}", target, actual])
            err = "" if actual is None else f"{actual - target:+d}"
            print(f"\rt = {t:6.2f}/{traj.duration:.2f} s   target {target:8d}   actual {actual}   error {err}      ",
                  end="", flush=True)
            if t >= traj.duration:
                break
            next_tick += period
            time.sleep(max(0.0, next_tick - time.monotonic()))
        print()
        if not go_to(traj.x[-1] + offset, 10, "Settling at end"):
            print("Warning: did not fully reach the final position.")
        print("Done.")
    except KeyboardInterrupt:
        print("\nInterrupted: stopping the cart.")
    finally:
        link.send("S")
        quiet_since, last = time.monotonic(), link.pos
        end = time.monotonic() + 4
        while time.monotonic() < end:
            time.sleep(0.05)
            p = link.poll()
            if p != last:
                last, quiet_since = p, time.monotonic()
            elif time.monotonic() - quiet_since > 0.4:
                break
        ser.close()
        if log:
            log.close()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Play a time/position file (Excel or CSV) on the belt cart.")
    ap.add_argument("file", help=".xlsx or .csv file with a time column and a position column")
    ap.add_argument("--sheet", help="Excel sheet name (default: the active sheet)")
    ap.add_argument("--time-col", help="time column: header name or 1-based number (default: auto-detect)")
    ap.add_argument("--pos-col", help="position column: header name or 1-based number (default: auto-detect)")
    ap.add_argument("--time-units", choices=TIME_TO_S, default="s", help="units of the time column (default s)")
    ap.add_argument("--units", choices=["steps"] + list(POS_TO_MM), default="steps",
                    help="units of the position column (default steps)")
    ap.add_argument("--steps-per-mm", type=float, help="motor steps per mm of belt travel (needed for mm/cm/m/in)")
    ap.add_argument("--mode", choices=["linear", "hold"], default="linear",
                    help="linear: glide between rows; hold: jump to each position and wait for the next row")
    ap.add_argument("--absolute", action="store_true",
                    help="treat positions as absolute (0 = the Arduino's zero at power-up). "
                         "Default: relative, so the first row is wherever the cart is now")
    ap.add_argument("--lead", type=float, default=0.0, help="aim this many seconds ahead to offset cart lag")
    ap.add_argument("--rate", type=float, default=20.0, help="commands per second (default 20)")
    ap.add_argument("--max-speed", type=float, default=2000.0,
                    help=f"speed limit in steps/s (default 2000, firmware cap {FIRMWARE_SPEED_CAP:.0f})")
    ap.add_argument("--min-steps", type=int, help="refuse to run if the path goes below this position")
    ap.add_argument("--max-steps", type=int, help="refuse to run if the path goes above this position")
    ap.add_argument("--log", help="write target-vs-actual positions to this CSV")
    ap.add_argument("--port", help="serial port (default: auto-detect)")
    ap.add_argument("--dry-run", action="store_true", help="load and check the file, but do not touch the hardware")
    ap.add_argument("--yes", action="store_true", help="skip the Press Enter confirmation")
    args = ap.parse_args(argv)
    if args.max_speed > FIRMWARE_SPEED_CAP:
        ap.error(f"--max-speed cannot exceed the firmware cap of {FIRMWARE_SPEED_CAP:.0f}")
    if not 1 <= args.rate <= 50:
        ap.error("--rate must be between 1 and 50")
    return args


def main():
    args = parse_args()
    traj = load_trajectory(args)
    problems = report(traj, args, "absolute" if args.absolute else "relative to where the cart starts")
    if problems:
        sys.exit("\n" + "\n".join(problems))
    if args.dry_run:
        print("\nDry run: file looks good, nothing was sent to the cart.")
        return
    run(args, traj)


if __name__ == "__main__":
    main()
