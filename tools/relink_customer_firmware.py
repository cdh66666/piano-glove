"""Recompile the supplied LGPL library and relink supplied application objects.

SPDX-License-Identifier: MIT
This engineering helper has no serial I/O. It does not contain proprietary
application source; the application is provided as linkable object files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(command, root):
    # GCC response files avoid Windows command-length limits. This is argv
    # quoting for GCC's own response parser, never shell command composition.
    arguments = root / 'compiler-arguments.txt'
    arguments.write_text('\n'.join('"' + str(item).replace('\\', '/').replace('"', '\\"') + '"'
                                   for item in command[1:]), encoding='utf-8')
    subprocess.run([str(command[0]), '@' + str(arguments)], check=True, cwd=root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, default=Path.home() / '.platformio' / 'packages',
                        help='PlatformIO packages directory with the pinned ESP32 framework/toolchain')
    parser.add_argument('--output', type=Path, required=True, help='New output directory; no existing output is overwritten')
    parser.add_argument('--existing-library', action='store_true', help='Verify original link objects without recompiling the library')
    parser.add_argument('--library-source', type=Path, help='Modified WebServerBinary source; default is adjacent supplied source')
    args = parser.parse_args(argv)
    bundle = Path(__file__).resolve().parent
    recipe = json.loads((bundle / 'recipe.json').read_text(encoding='utf-8'))
    packages = args.packages.resolve()
    framework = packages / 'framework-arduinoespressif32'
    toolchain = packages / 'toolchain-xtensa-esp32'
    tools = toolchain / 'bin'
    compiler = tools / 'xtensa-esp32-elf-g++.exe'
    ar = tools / 'xtensa-esp32-elf-ar.exe'
    if not compiler.is_file() or not (framework / 'package.json').is_file():
        raise RuntimeError('Install PlatformIO espressif32@6.4.0 framework/toolchain packages first; see README.')
    metadata = json.loads((framework / 'package.json').read_text(encoding='utf-8'))
    if metadata.get('version') != recipe['framework_version']:
        raise RuntimeError('Pinned Arduino-ESP32 framework version differs; use ' + recipe['framework_version'])
    source = args.library_source.resolve() if args.library_source else bundle.parent / 'WebServerBinary'
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError('Output already exists; choose a new path.')
    output.mkdir(parents=True)
    # ASCII temporary paths work with older Xtensa Windows compiler builds.
    with tempfile.TemporaryDirectory(prefix='pg-relink-') as temporary:
        root = Path(temporary)
        shutil.copytree(bundle / 'objects', root / 'objects')
        shutil.copytree(bundle / 'archives', root / 'archives')
        shutil.copytree(source, root / 'WebServerBinary')
        library = root / 'archives' / recipe['webserver_archive']
        if not args.existing_library:
            compiled = []
            include_dirs = [root / 'WebServerBinary' / 'src']
            include_dirs += [framework / path for path in recipe['framework_includes']]
            include_dirs += [framework / 'libraries' / name / 'src' for name in ('WiFi', 'FS', 'SPIFFS', 'Preferences', 'DNSServer')]
            defines = []
            for item in recipe['defines']:
                if isinstance(item, list):
                    value = str(item[1]).replace('\\', '')
                    if value == '$BOARD_F_CPU':
                        value = '240000000L'
                    defines.append('-D' + item[0] + '=' + value)
                else:
                    defines.append('-D' + item)
            for index, filename in enumerate(recipe['library_sources']):
                target = root / ('library-%d.o' % index)
                command = [compiler, '-c', '-o', target] + recipe['cxx_flags'] + recipe['cc_flags'] + defines
                command += ['-I' + path.as_posix() for path in include_dirs]
                command += [root / 'WebServerBinary' / filename]
                run(command, root)
                compiled.append(target)
            library.unlink()
            subprocess.run([str(ar), 'rc', str(library)] + [str(path) for path in compiled], check=True)
        sdk = framework / 'tools' / 'sdk' / 'esp32'
        elf = root / 'relinked.elf'
        command = [compiler, '-o', elf] + recipe['link_flags'] + ['-Wl,-Map=' + (root / 'relinked.map').as_posix()]
        command += [root / 'objects' / name for name in recipe['application_objects']]
        command += ['-L' + str(sdk / part).replace('\\', '/') for part in ('lib', 'ld', 'dio_qspi')]
        command += ['-Wl,--start-group']
        command += [root / 'archives' / name for name in recipe['local_archives']]
        command += recipe['sdk_libraries'] + ['-Wl,--end-group']
        run(command, root)
        binary = root / 'relinked.bin'
        # esptool here is an independently installed official conversion tool,
        # not the customer main application. elf2image has no serial I/O.
        esptool = packages / 'tool-esptoolpy' / 'esptool.py'
        subprocess.run([sys.executable, str(esptool), '--chip', 'esp32', 'elf2image',
                        '--flash_mode', 'dio', '--flash_freq', '40m', '--flash_size', '4MB',
                        '--elf-sha256-offset', '0xb0', '-o', str(binary), str(elf)], check=True)
        shutil.copy2(elf, output / 'firmware.elf')
        shutil.copy2(binary, output / 'firmware.bin')
        report = dict(ok=True, serial_opened=False, application_source_included=False,
                      library_recompiled=not args.existing_library,
                      firmware_bytes=binary.stat().st_size,
                      firmware_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
        (output / 'relink-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
