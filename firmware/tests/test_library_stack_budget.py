"""Check compiled ESP32 call frames and the actual loop-stack constant.

Run after pio run -d firmware. This is a compile-time budget, not a measurement
of SPIFFS GC, interrupt-stack use, or board behavior.
"""
from pathlib import Path
import json
import re
import subprocess

root = Path(__file__).resolve().parents[1]
elf = root / '.pio/build/esp32dev/firmware.elf'
toolchain = Path('C:/Users/admin/.platformio/packages/toolchain-xtensa-esp32/bin')
nm = toolchain / 'xtensa-esp32-elf-nm.exe'
objdump = toolchain / 'xtensa-esp32-elf-objdump.exe'
symbols = subprocess.check_output([str(nm), '-C', str(elf)], text=True)


def symbol(fragment):
    matches = [line for line in symbols.splitlines() if fragment in line]
    assert len(matches) == 1, matches
    return int(matches[0].split()[0], 16)


def disassembly(address):
    return subprocess.check_output([str(objdump), '-d', '-C', '--start-address=' + hex(address),
                                    '--stop-address=' + hex(address + 20), str(elf)], text=True)


frames = {}
for name, fragment, budget in [('cmdLine', '_ZL7cmdLinePc', 1024),
                              ('command', 'library::command(int, char**)', 1024),
                              ('commit', 'library::commit()', 640),
                              ('openScore', '_ZN7libraryL9openScore', 256),
                              ('openScorePath', 'library::openScorePath(', 256),
                              ('readScoreUsb', 'library::readScoreUsb(', 640)]:
    match = re.search(r'entry\s+a1,\s+(0x[0-9a-f]+|\d+)', disassembly(symbol(fragment)))
    assert match, name
    frame = int(match[1], 0)
    assert frame <= budget, (name, frame, budget)
    frames[name] = frame
# READ and COMMIT are exclusive LIB actions. Account for each actual named
# call path, rather than adding the two mutually exclusive helper frames.
paths = {action: sum(frames[name] for name in ['cmdLine', 'command', helper, 'openScore', 'openScorePath'])
         for action, helper in [('commit', 'commit'), ('read', 'readScoreUsb')]}
assert max(paths.values()) <= 3000, (frames, paths)
loop_code = disassembly(symbol('getArduinoLoopTaskStackSize()'))
literal = re.search(r'l32r\s+a2,\s+([0-9a-f]+)', loop_code)
assert literal, loop_code
address = int(literal[1], 16)
dump = subprocess.check_output([str(objdump), '-s', '-j', '.flash.text', '--start-address=' + hex(address),
                               '--stop-address=' + hex(address + 4), str(elf)], text=True)
word = re.search(r'\s' + hex(address)[2:] + r'\s+([0-9a-f]{8})\s', dump)
assert word, dump
loop_bytes = int.from_bytes(bytes.fromhex(word[1]), 'little')
assert loop_bytes == 16384, loop_bytes
print(json.dumps({'result': 'PASS_COMPILED_STACK_BUDGET_ONLY', 'frames_bytes': frames,
                  'named_call_path_bytes': paths, 'loop_stack_bytes': loop_bytes}))
