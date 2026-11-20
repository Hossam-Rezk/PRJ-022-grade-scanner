# PRJ-022 Grade Scanner - Pico 2 W firmware (main.py)
# -----------------------------------------------------------------
# Runs by itself every time the Pico gets power. It waits for text
# commands from scanner.py on the PC (over the USB cable), moves the
# paper with the two stepper motors, watches the four IR sensors and
# shows the machine state on the RGB LED and the buzzer.
#
# Every reply is one line that starts with OK, ERR or EVT:
#   OK ...   the command worked
#   ERR ...  the command failed (the words after ERR say why)
#   EVT ...  something happened by itself (power-on, paper inserted)
#
# Commands (type them in Thonny's Shell to test by hand):
#   PING                 -> OK PONG
#   STATUS               -> state, sensors, motors
#   SENSORS              -> OK SENSORS 1 0 0 0   (1 = sensor sees paper)
#   FEED                 -> pull the next sheet in and stop it under the camera
#   EJECT                -> push the sheet out, report its length
#   JOG 1 50             -> turn motor 1 so the paper moves 50 mm (2 = motor 2,
#                           B = both, negative = backwards)
#   LED green            -> red green blue yellow cyan magenta white off
#   BEEP 2               -> beep twice
#   MOTORS OFF           -> let the motors turn freely
#   RESET                -> clear an error after you removed a jammed sheet
#   STOP                 -> stop a moving motor at once
# All settings live in config.py.

import sys
import time
import select
from machine import Pin, PWM
import config as C

VERSION = "1.0"

# ---------------------------------------------------------------- units
STEPS_PER_MM = (C.MOTOR_STEPS_PER_TURN * C.MICROSTEPS /
                (3.14159265 * C.ROLLER_DIAMETER_MM) * C.DISTANCE_CORRECTION)


def mm_to_steps(mm):
    return int(abs(mm) * STEPS_PER_MM + 0.5)


DEBOUNCE_STEPS = max(1, mm_to_steps(C.DEBOUNCE_MM))

# ---------------------------------------------------------------- pins
m1_step = Pin(C.M1_STEP_PIN, Pin.OUT, value=0)
m1_dir = Pin(C.M1_DIR_PIN, Pin.OUT, value=0)
m1_en = Pin(C.M1_EN_PIN, Pin.OUT, value=1)       # 1 = motor free (EN is active LOW)
m2_step = Pin(C.M2_STEP_PIN, Pin.OUT, value=0)
m2_dir = Pin(C.M2_DIR_PIN, Pin.OUT, value=0)
m2_en = Pin(C.M2_EN_PIN, Pin.OUT, value=1)

ir_pins = [Pin(p, Pin.IN, Pin.PULL_UP)
           for p in (C.IR1_PIN, C.IR2_PIN, C.IR3_PIN, C.IR4_PIN)]
IR_NAMES = ("IR1", "IR2", "IR3", "IR4")

rgb = [PWM(Pin(p)) for p in (C.RGB_RED_PIN, C.RGB_GREEN_PIN, C.RGB_BLUE_PIN)]
for _p in rgb:
    _p.freq(1000)

if C.BUZZER_PASSIVE:
    buzzer = PWM(Pin(C.BUZZER_PIN))
    buzzer.freq(2000)
    buzzer.duty_u16(0)
else:
    buzzer = Pin(C.BUZZER_PIN, Pin.OUT, value=0)

# ---------------------------------------------------------------- state
IDLE, HOLDING, ERROR = "IDLE", "HOLDING", "ERROR"
state = IDLE
motors_enabled = False
hold_since = 0
covered_steps = 0          # steps the sheet has travelled past IR3 so far


class Stopped(Exception):
    pass


# ---------------------------------------------------------------- sensors
def seen(i):
    """True when IR sensor i (0 to 3) sees paper."""
    v = ir_pins[i].value()
    return v == 0 if C.IR_ACTIVE_LOW else v == 1


def sensors():
    return [1 if seen(i) else 0 for i in range(4)]


class Watch:
    """Debounced view of one sensor. update() is called once per motor step
    and returns True on the step where the debounced state changes."""

    def __init__(self, i):
        self.i = i
        self.state = seen(i)
        self.count = 0

    def update(self):
        if seen(self.i) != self.state:
            self.count += 1
            if self.count >= DEBOUNCE_STEPS:
                self.state = not self.state
                self.count = 0
                return True
        else:
            self.count = 0
        return False


# ---------------------------------------------------------------- LED and buzzer
COLOURS = {
    "off": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1),
    "yellow": (1, 0.5, 0), "cyan": (0, 1, 1), "magenta": (1, 0, 1), "white": (1, 1, 1),
}


def led(name):
    levels = COLOURS.get(name, (0, 0, 0))
    for pwm, level in zip(rgb, levels):
        duty = int(level * 65535)
        if C.RGB_COMMON_ANODE:
            duty = 65535 - duty
        pwm.duty_u16(duty)


def buzz(on):
    if C.BUZZER_PASSIVE:
        buzzer.duty_u16(32768 if on else 0)
    else:
        buzzer.value(1 if on else 0)


def beep(n=1, on_ms=80, off_ms=90):
    for k in range(n):
        buzz(True)
        time.sleep_ms(on_ms)
        buzz(False)
        if k < n - 1:
            time.sleep_ms(off_ms)


# ---------------------------------------------------------------- motors
def motors_on(use1=True, use2=True):
    global motors_enabled
    m1_en.value(0 if use1 else 1)
    m2_en.value(0 if use2 else 1)
    motors_enabled = use1 or use2
    time.sleep_ms(2)


def motors_off():
    global motors_enabled
    m1_en.value(1)
    m2_en.value(1)
    motors_enabled = False


def set_direction(forward):
    m1_dir.value((0 if forward else 1) ^ (1 if C.M1_REVERSE else 0))
    m2_dir.value((0 if forward else 1) ^ (1 if C.M2_REVERSE else 0))
    time.sleep_us(5)


# ---------------------------------------------------------------- commands from the PC
_poll = select.poll()
_poll.register(sys.stdin, select.POLLIN)
_buf = []


def read_line():
    """Return one complete line from the PC, or None if nothing is waiting."""
    while _poll.poll(0):
        ch = sys.stdin.read(1)
        if not ch:
            break
        if ch in "\r\n":
            if _buf:
                line = "".join(_buf).strip()
                del _buf[:]
                return line
        elif len(_buf) < 80:
            _buf.append(ch)
    return None


def check_stop():
    line = read_line()
    if line is None:
        return
    if line.upper() == "STOP":
        raise Stopped()
    print("ERR BUSY ignored '%s' while moving" % line)


def move(mm, speed, use1=True, use2=True, forward=True, until=None):
    """Turn the motors so the paper travels up to `mm` millimetres.
    `until(i)` is called after every step; when it returns True the move
    ends early. Returns the number of steps done."""
    n = mm_to_steps(mm)
    if n == 0:
        return 0
    set_direction(forward)
    motors_on(use1, use2)
    v0 = max(1.0, C.START_SPEED * STEPS_PER_MM)          # steps per second
    v1 = max(v0, speed * STEPS_PER_MM)
    ramp = max(1, mm_to_steps(C.ACCEL_MM))
    dv = (v1 - v0) / ramp
    fast_period = int(1000000 / v1)
    s1_on, s1_off = m1_step.on, m1_step.off
    s2_on, s2_off = m2_step.on, m2_step.off
    ticks_us, ticks_diff, ticks_add = time.ticks_us, time.ticks_diff, time.ticks_add
    t = ticks_us()
    for i in range(n):
        period = int(1000000 / (v0 + dv * i)) if i < ramp else fast_period
        while ticks_diff(t, ticks_us()) > 0:
            pass
        if use1:
            s1_on()
        if use2:
            s2_on()
        time.sleep_us(2)                 # DRV8825 needs at least 1.9 us
        if use1:
            s1_off()
        if use2:
            s2_off()
        now = ticks_us()
        t = ticks_add(t, period)
        if ticks_diff(now, t) > period:  # running late: do not rush to catch up
            t = now
        if until is not None and until(i):
            return i + 1
        if (i & 255) == 255:
            check_stop()
    return n


# ---------------------------------------------------------------- jobs
def fail(code, detail):
    global state
    motors_off()
    state = ERROR
    led("red")
    beep(3, 250, 150)
    return "ERR %s %s" % (code, detail)


def cmd_feed():
    global state, hold_since, covered_steps
    if state == ERROR:
        return "ERR NEEDS_RESET clear the paper path, then send RESET"
    if state == HOLDING or seen(1) or seen(2):
        return "ERR SHEET_PRESENT a sheet is already inside, send EJECT first"
    if not seen(0):
        return "ERR NO_PAPER IR1 sees no sheet"
    led("blue")
    # 1. fast until IR2 sees the leading edge
    w2 = Watch(1)
    done = move(C.FEED_MAX_MM, C.FEED_SPEED,
                until=lambda i: w2.update() and w2.state)
    if not w2.state:
        return fail("JAM", "FEED IR2 never saw the sheet")
    # 2. slow until IR3 sees the leading edge
    left_mm = C.FEED_MAX_MM - done / STEPS_PER_MM
    w3 = Watch(2)
    move(left_mm, C.SLOW_SPEED, until=lambda i: w3.update() and w3.state)
    if not w3.state:
        return fail("JAM", "FEED IR3 never saw the sheet")
    # 3. optional extra travel, then hold the sheet still under the camera
    covered_steps = move(C.SCAN_STOP_OFFSET_MM, C.SLOW_SPEED) if C.SCAN_STOP_OFFSET_MM > 0 else 0
    state = HOLDING
    hold_since = time.ticks_ms()
    led("cyan")
    return "OK FEED sheet ready under the camera"


def cmd_eject():
    global state, covered_steps
    if not (seen(1) or seen(2) or seen(3)) and state != HOLDING:
        return "ERR NO_SHEET nothing to eject"
    led("blue")
    measure = state == HOLDING
    w3 = Watch(2)
    w4 = Watch(3)
    info = [None, w4.state]          # [length in steps, IR4 has seen the sheet]

    def until(i):
        if w3.update() and not w3.state and info[0] is None:
            info[0] = covered_steps + i + 1
        if w4.update():
            if w4.state:
                info[1] = True
            elif info[1]:
                return True          # trailing edge has passed IR4
        return False

    move(C.EJECT_MAX_MM, C.FEED_SPEED, until=until)
    if w4.state or not info[1]:
        return fail("JAM", "EJECT the sheet did not pass IR4")
    move(C.EJECT_EXTRA_MM, C.FEED_SPEED)
    motors_off()
    covered_steps = 0
    state = IDLE
    led("green")
    if measure and info[0] is not None:
        return "OK EJECT length_mm=%.1f" % (info[0] / STEPS_PER_MM)
    return "OK EJECT length_mm=0"


def cmd_jog(args):
    if len(args) < 2:
        return "ERR BAD_COMMAND use JOG 1|2|B <mm> [speed]"
    which = args[0].upper()
    if which not in ("1", "2", "B"):
        return "ERR BAD_COMMAND motor must be 1, 2 or B"
    try:
        mm = float(args[1])
        speed = float(args[2]) if len(args) > 2 else C.FEED_SPEED
    except ValueError:
        return "ERR BAD_COMMAND distance must be a number"
    if abs(mm) > 300:
        return "ERR BAD_COMMAND at most 300 mm per JOG"
    steps = move(abs(mm), speed, use1=which in ("1", "B"), use2=which in ("2", "B"),
                 forward=mm >= 0)
    if state != HOLDING:
        motors_off()
    return "OK JOG %s %.1f mm (%d steps)" % (which, mm, steps)


def status_line():
    return "OK STATUS state=%s ir=%s motors=%s steps_per_mm=%.2f version=%s" % (
        state, ",".join(str(s) for s in sensors()), "on" if motors_enabled else "off",
        STEPS_PER_MM, VERSION)


def handle(line):
    global state
    parts = line.split()
    if not parts:
        return None
    cmd, args = parts[0].upper(), parts[1:]
    try:
        if cmd == "PING":
            return "OK PONG PRJ-022 v%s" % VERSION
        if cmd == "STATUS":
            return status_line()
        if cmd == "SENSORS":
            return "OK SENSORS %s" % " ".join(str(s) for s in sensors())
        if cmd == "FEED":
            return cmd_feed()
        if cmd == "EJECT":
            return cmd_eject()
        if cmd == "JOG":
            return cmd_jog(args)
        if cmd == "LED":
            if not args or args[0].lower() not in COLOURS:
                return "ERR BAD_COMMAND colours: %s" % " ".join(COLOURS)
            led(args[0].lower())
            return "OK LED %s" % args[0].lower()
        if cmd == "BEEP":
            n = int(args[0]) if args else 1
            beep(max(1, min(n, 5)))
            return "OK BEEP %d" % n
        if cmd == "MOTORS":
            if args and args[0].upper() == "ON":
                motors_on()
                return "OK MOTORS on"
            motors_off()
            return "OK MOTORS off"
        if cmd == "RESET":
            motors_off()
            state = IDLE
            led("green")
            return "OK RESET"
        if cmd == "STOP":
            motors_off()
            return "OK STOP nothing was moving"
        if cmd == "HELP":
            return ("OK HELP PING STATUS SENSORS FEED EJECT JOG LED BEEP MOTORS RESET STOP")
        return "ERR BAD_COMMAND unknown '%s', send HELP" % cmd
    except Stopped:
        motors_off()
        state = ERROR
        led("yellow")
        return "ERR STOPPED motors stopped by the PC, send RESET"
    except ValueError:
        return "ERR BAD_COMMAND could not read a number"


# ---------------------------------------------------------------- main loop
def main():
    global hold_since
    motors_off()
    for colour in ("red", "green", "blue"):
        led(colour)
        time.sleep_ms(150)
    led("green")
    beep(1)
    print("EVT BOOT PRJ-022 v%s steps_per_mm=%.2f" % (VERSION, STEPS_PER_MM))
    if seen(1) or seen(2) or seen(3):
        print("EVT SHEET_INSIDE a sheet is in the paper path, send EJECT")
    paper_in = seen(0)
    try:
        while True:
            line = read_line()
            if line:
                reply = handle(line)
                if reply:
                    print(reply)
            now_in = seen(0)
            if now_in and not paper_in and state == IDLE:
                print("EVT PAPER_IN")
            paper_in = now_in
            if (state == HOLDING and motors_enabled and
                    time.ticks_diff(time.ticks_ms(), hold_since) > C.HOLD_TIMEOUT_S * 1000):
                motors_off()
                print("EVT HOLD_RELEASED motors let go after %d s" % C.HOLD_TIMEOUT_S)
            time.sleep_ms(5)
    finally:
        motors_off()
        led("off")
        buzz(False)


try:
    _TEST_MODE           # defined only by the PC test harness
except NameError:
    main()
