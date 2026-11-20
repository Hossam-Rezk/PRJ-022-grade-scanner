# PRJ-022 Grade Scanner - hardware test (hwtest.py)
# -----------------------------------------------------------------
# Run this from Thonny (open it, then press the green Run button).
# It does NOT need to be saved on the Pico. It checks every part
# one by one and tells you what to look for. config.py must already
# be on the Pico.
#
# Before you start: battery switch ON, motors connected, nothing in
# the paper path, and the rollers free to turn.

import time
from machine import Pin, PWM
import config as C

STEPS_PER_MM = (C.MOTOR_STEPS_PER_TURN * C.MICROSTEPS /
                (3.14159265 * C.ROLLER_DIAMETER_MM) * C.DISTANCE_CORRECTION)

m = {
    1: (Pin(C.M1_STEP_PIN, Pin.OUT, value=0), Pin(C.M1_DIR_PIN, Pin.OUT, value=0),
        Pin(C.M1_EN_PIN, Pin.OUT, value=1), C.M1_REVERSE),
    2: (Pin(C.M2_STEP_PIN, Pin.OUT, value=0), Pin(C.M2_DIR_PIN, Pin.OUT, value=0),
        Pin(C.M2_EN_PIN, Pin.OUT, value=1), C.M2_REVERSE),
}
ir = [Pin(p, Pin.IN, Pin.PULL_UP) for p in (C.IR1_PIN, C.IR2_PIN, C.IR3_PIN, C.IR4_PIN)]
rgb = [PWM(Pin(p)) for p in (C.RGB_RED_PIN, C.RGB_GREEN_PIN, C.RGB_BLUE_PIN)]
for p in rgb:
    p.freq(1000)


def led(r, g, b):
    for pwm, level in zip(rgb, (r, g, b)):
        duty = level * 65535
        pwm.duty_u16(65535 - duty if C.RGB_COMMON_ANODE else duty)


def buzz(ms):
    if C.BUZZER_PASSIVE:
        b = PWM(Pin(C.BUZZER_PIN))
        b.freq(2000)
        b.duty_u16(32768)
        time.sleep_ms(ms)
        b.duty_u16(0)
    else:
        b = Pin(C.BUZZER_PIN, Pin.OUT)
        b.value(1)
        time.sleep_ms(ms)
        b.value(0)


def seen(i):
    v = ir[i].value()
    return v == 0 if C.IR_ACTIVE_LOW else v == 1


def turn(motor, mm, speed_mm_s=30):
    step, direction, enable, reverse = m[motor]
    direction.value((0 if mm >= 0 else 1) ^ (1 if reverse else 0))
    enable.value(0)
    time.sleep_ms(5)
    n = int(abs(mm) * STEPS_PER_MM)
    half = max(3, int(500000 / (speed_mm_s * STEPS_PER_MM)))
    for _ in range(n):
        step.value(1)
        time.sleep_us(half)
        step.value(0)
        time.sleep_us(half)
    enable.value(1)


def pause(text):
    print()
    print(">>> " + text)
    time.sleep(2)


print("PRJ-022 hardware test. Steps per mm = %.2f" % STEPS_PER_MM)

pause("TEST 1: buzzer. You should hear 2 beeps.")
buzz(150)
time.sleep_ms(150)
buzz(150)

pause("TEST 2: RGB LED. It shows red, green, blue, then white, 1 second each.")
for colour in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)):
    led(*colour)
    time.sleep(1)
led(0, 0, 0)
print("If the colours came in a different order, swap wires W46 to W48 or the pins in config.py.")

pause("TEST 3: IR sensors for 20 seconds. Hold a white sheet under each sensor in turn.")
print("1 = sees paper, 0 = sees nothing")
end = time.ticks_add(time.ticks_ms(), 20000)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    print("IR1 %d   IR2 %d   IR3 %d   IR4 %d" % tuple(1 if seen(i) else 0 for i in range(4)))
    time.sleep_ms(400)

pause("TEST 4: Motor 1 (feed rollers) turns FORWARD 50 mm, then back.")
turn(1, 50)
time.sleep_ms(500)
turn(1, -50)

pause("TEST 5: Motor 2 (exit rollers) turns FORWARD 50 mm, then back.")
turn(2, 50)
time.sleep_ms(500)
turn(2, -50)

print()
print("Done. FORWARD means the rollers pull a paper strip toward the exit.")
print("If a motor went the wrong way first, set M1_REVERSE or M2_REVERSE = True in config.py.")
print("If a motor only buzzed, check its coil pairs (Hardware Wiring Guide, Step L).")
