"""PRJ-022 Grade Scanner - copies the firmware to the Pico over USB.
Run by setup_pico.bat."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PICO_FILES = os.path.join(os.path.dirname(HERE), "pico")
sys.path.insert(0, HERE)

import scanner  # noqa: E402  (the existing PC program: Pico link and USB id)


def find_port():
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == scanner.PICO_USB_VENDOR:
            return p.device
    return None


def mpremote(port, *args, capture=False):
    cmd = [sys.executable, "-m", "mpremote", "connect", port] + list(args)
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=60)


def same_text(a, b):
    return a.replace("\r\n", "\n").strip() == b.replace("\r\n", "\n").strip()


def main():
    print("PRJ-022 Pico setup")
    print("------------------")
    port = find_port()
    if not port:
        print("PROBLEM: no Pico found on USB.")
        print("  1. Check the USB cable (it must be a data cable, not charge-only).")
        print("  2. If this Pico has never run MicroPython: unplug it, hold the BOOTSEL button,")
        print("     plug it in, and copy the Pico 2 W MicroPython .uf2 file from")
        print("     https://micropython.org/download/RPI_PICO2_W/ onto the drive that appears.")
        print("  3. Run this file again.")
        return 1
    print("Pico found on %s." % port)

    try:
        probe = mpremote(port, "exec", "print('hello')", capture=True)
    except subprocess.TimeoutExpired:
        probe = None
    if probe is None or probe.returncode != 0:
        print("PROBLEM: the Pico is busy or does not answer.")
        print("  Close Thonny and any other program using the Pico, unplug and replug it,")
        print("  then run this file again.")
        if probe is not None and probe.stderr:
            print("  Details: " + probe.stderr.strip().splitlines()[-1])
        return 1

    local_config = os.path.join(PICO_FILES, "config.py")
    copy_config = True
    on_pico = mpremote(port, "cat", ":config.py", capture=True)
    if on_pico.returncode == 0:
        with open(local_config, encoding="utf-8") as f:
            if same_text(f.read(), on_pico.stdout):
                copy_config = False
                print("config.py on the Pico is already the same as pico\\config.py.")
            else:
                print()
                print("The Pico already has a config.py that is DIFFERENT from pico\\config.py.")
                print("It may hold your calibration (motor direction, roller size, distances).")
                answer = input("Replace it with pico\\config.py? Type y to replace, Enter to keep: ")
                copy_config = answer.strip().lower() == "y"
                print("config.py will be %s." % ("replaced" if copy_config else "kept as it is"))

    names = (["config.py"] if copy_config else []) + ["main.py"]
    for name in names:
        print("Copying %s to the Pico..." % name)
        r = mpremote(port, "cp", os.path.join(PICO_FILES, name), ":" + name)
        if r.returncode != 0:
            print("PROBLEM: could not copy %s." % name)
            return 1

    print("Restarting the Pico...")
    mpremote(port, "reset", capture=True)
    link = None
    for _ in range(6):
        time.sleep(2)
        try:
            link = scanner.PicoLink()
            break
        except scanner.PicoError as e:
            problem = str(e)
    if link is None:
        print("PROBLEM: the files were copied, but the Pico does not answer: %s" % problem)
        return 1
    print("The Pico answers on %s: %s" % (link.port, link.version))
    try:
        print("  " + link.send("STATUS"))
        print("  " + link.send("SENSORS") + "   (1 = sensor sees paper)")
        link.send("BEEP 1")
    except scanner.PicoError as e:
        print("  (status not read: %s)" % e)
    link.close()
    print()
    print("Setup finished. You can now run start_server.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
