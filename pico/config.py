# PRJ-022 Grade Scanner - settings for the Pico 2 W
# ---------------------------------------------------------------
# Change values here, not in main.py. Save this file to the Pico
# again after every change (File > Save as > Raspberry Pi Pico).
# The pin numbers match the Hardware Wiring Guide. Do not change a
# pin here unless you also moved the wire on the breadboard.

# ---- Motor driver pins (DRV8825) ------------------------------
M1_STEP_PIN = 16      # Motor 1 (feed rollers)  STEP  - wire W4
M1_DIR_PIN = 17       # Motor 1                 DIR   - wire W5
M1_EN_PIN = 18        # Motor 1                 EN    - wire W6
M2_STEP_PIN = 19      # Motor 2 (exit rollers)  STEP  - wire W11
M2_DIR_PIN = 20       # Motor 2                 DIR   - wire W12
M2_EN_PIN = 21        # Motor 2                 EN    - wire W13

# ---- IR paper sensors -----------------------------------------
IR1_PIN = 22          # entry      - wire W26
IR2_PIN = 26          # slow-down, about 30 mm before IR3 - wire W29
IR3_PIN = 27          # scan stop  - wire W32
IR4_PIN = 28          # exit check, just before the exit rollers - wire W35
# Most modules give LOW (0 V) when they see paper. If yours give HIGH,
# set this to False.
IR_ACTIVE_LOW = True

# ---- Buzzer and RGB LED ---------------------------------------
BUZZER_PIN = 15       # wire W36
BUZZER_PASSIVE = False    # True if the buzzer only clicks (passive type)
RGB_RED_PIN = 12      # wire W46
RGB_GREEN_PIN = 11    # wire W47
RGB_BLUE_PIN = 10     # wire W48
RGB_COMMON_ANODE = False  # True if Step H found a common-anode LED

# ---- Motor direction ------------------------------------------
# If a motor turns the wrong way (pulls the paper backwards), set its
# value to True. No rewiring needed.
M1_REVERSE = False
M2_REVERSE = False

# ---- Rollers and step size ------------------------------------
MOTOR_STEPS_PER_TURN = 200    # standard NEMA 17 (1.8 degrees per step)
MICROSTEPS = 8                # set by wiring: M0 and M1 HIGH = 1/8 step
ROLLER_DIAMETER_MM = 12.0     # measure YOUR driven roller, rubber included
# Fine correction after the 100 mm test in the Software Setup Guide.
# 1.0 = no correction. Example: paper moved 96 mm instead of 100 -> 100/96 = 1.042
DISTANCE_CORRECTION = 1.0

# ---- Speeds (millimetres per second) --------------------------
FEED_SPEED = 60.0       # normal paper speed
SLOW_SPEED = 20.0       # speed between IR2 and IR3, for an accurate stop
START_SPEED = 10.0      # speed at the start of every move (gentle start)
ACCEL_MM = 8.0          # distance over which the speed ramps up

# ---- Paper path (millimetres) ---------------------------------
SCAN_STOP_OFFSET_MM = 0.0   # extra travel after IR3 sees the sheet edge
FEED_MAX_MM = 400.0         # longest allowed travel to reach IR3 (else JAM)
EJECT_MAX_MM = 500.0        # longest allowed travel to push the sheet out
EJECT_EXTRA_MM = 40.0       # keep turning after IR4 is clear: distance from IR4 to
                            # the exit rollers, plus about 20 mm
DEBOUNCE_MM = 0.5           # a sensor must agree this long before it counts

# ---- Holding ---------------------------------------------------
# While a sheet waits under the camera the motors hold it still.
# After this many seconds without a command they let go (cooler motors).
HOLD_TIMEOUT_S = 60
