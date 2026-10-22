"""Freeze an explicitly dated, runtime-only Windows customer test package.

No device, serial port, service, GitHub, or customer messaging is touched.
Run after the source and optional compiled firmware have been frozen.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
HOST = REPO / 'host'
DATE = '20261022'
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
MODULES = ['bridge.py', 'calibration_recordings.py', 'customer_runtime.py',
           'score_codec.py', 'score_converter.py', 'score_converter_engine.py']
FORBIDDEN_EXTENSIONS = {'.step', '.stp', '.stl', '.f3d', '.xlsx', '.docx', '.pdf', '.ino', '.cpp', '.h', '.py'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_imports(name):
    """Include local PDF adapters imported by the converter after its migration."""
    tree = ast.parse((HOST / name).read_text(encoding='utf-8-sig'))
    output = []
    for node in ast.walk(tree):
        imports = [node.module] if isinstance(node, ast.ImportFrom) else [x.name for x in node.names] if isinstance(node, ast.Import) else []
        for item in imports:
            if item and (HOST / (item + '.py')).is_file() and item != 'firmware_flash':
                output.append(item + '.py')
    return output


def source_modules():
    output = set(MODULES)
    waiting = list(output)
    while waiting:
        for name in local_imports(waiting.pop()):
            if name not in output:
                output.add(name)
                waiting.append(name)
    return sorted(output)


def prepare(work):
    stage = work / 'stage'
    if stage.exists():
        raise RuntimeError('构建目录已有 stage；请使用新的工作目录，避免覆盖旧验证记录。')
    stage.mkdir(parents=True)
    modules = source_modules()
    input_hashes = {}
    for name in modules:
        source = HOST / name
        text = source.read_text(encoding='utf-8-sig')
        # A closed customer test package must not silently reintroduce PyMuPDF.
        if re.search(r'^\s*(?:import\s+(?:fitz|pymupdf)\b|from\s+(?:fitz|pymupdf)\b)', text, re.M):
            raise RuntimeError(name + ' 仍依赖 PyMuPDF；先完成宽松许可 PDF 后端替换，再构建客户包。')
        input_hashes['host/' + name] = sha256(source)
        if name == 'bridge.py':
            marker = 'HOST_DIR = os.path.dirname(os.path.abspath(__file__))'
            if text.count(marker) != 1:
                raise RuntimeError('bridge HOST_DIR 结构已变，需复核冻结适配。')
            text = text.replace(marker, marker + '\nRUNTIME_DATA_DIR = HOST_DIR')
            target = 'os.path.join(HOST_DIR, "calibration_recordings"'
            if text.count(target) != 3:
                raise RuntimeError('bridge 校准记录路径结构已变，需复核冻结适配。')
            text = text.replace(target, 'os.path.join(RUNTIME_DATA_DIR, "calibration_recordings"')
        (stage / name).write_text(text, encoding='utf-8')
    # Firmware build/maintenance stays out of the customer executable. An
    # optional vendor-approved compiled application image is handled separately.
    (stage / 'firmware_flash.py').write_text('''import functools
def exclusive(method):
    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        with self._maintenance_lock:
            return method(self, *args, **kwargs)
    return guarded
class FirmwareManager:
    serialExclusive = False
    busy = False
    owner = None
    def __init__(self, bridge): self.bridge = bridge
    def status(self):
        return dict(state='idle', phase='idle', progress=0, busy=False,
                    serialExclusive=False, available=False, verified=False,
                    version='2.2.4', log=[], error='', customerEdition=True)
    def start(self, action, body):
        raise RuntimeError('测试版不提供固件源码构建，请按供应方升级说明操作。')
''', encoding='utf-8')
    web = stage / 'web'
    web.mkdir()
    assets = ['software.html', 'software.js', 'software.css', 'software-audio.js', 'software-pack.js', 'software-review.js', 'software-review.css', 'software-tempo.js', 'software-tempo.css', 'software-upload.js', 'software-upload.css', 'web_piano_glove.html', 'calibration_trace.html', 'usb-driver.js', 'usb-driver.css']
    assets += [p.name for p in HOST.glob('delivery-*.js')]
    assets += [p.name for p in HOST.glob('delivery-*.css')]
    for name in assets:
        shutil.copy2(HOST / name, web / name)
        input_hashes['host/' + name] = sha256(HOST / name)
    for source in (HOST / 'assets').rglob('*'):
        if source.is_file() and source.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.svg'}:
            relative = source.relative_to(HOST)
            target = web / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            input_hashes['host/' + relative.as_posix()] = sha256(source)
    with (web / 'delivery-shell.css').open('a', encoding='utf-8') as target:
        target.write('\n#demoFlash,#fwOpen,#fwDialog,#demoFirmwareDialog{display:none!important}\n')
    (work / 'source-snapshot.json').write_text(json.dumps(input_hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    return stage, input_hashes


def copy_notices(target, names=('pyserial', 'pypdfium2', 'pypdf', 'Pillow')):
    root = target / '第三方许可'
    root.mkdir()
    for candidate in (Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE'):
        if candidate.is_file():
            shutil.copy2(candidate, root / 'Python-LICENSE.txt')
            break
    versions = {}
    for name in names:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        versions[name] = dist.version
        notice_dir = root / name
        notice_dir.mkdir()
        for item in dist.files or []:
            lower = str(item).lower()
            if any(marker in lower for marker in ('license', 'copying', 'notice', 'authors')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    # Preserve relative names so third-party PDFium notices do
                    # not collapse into a single overwritten LICENSE file.
                    relative = Path(str(item))
                    if '..' in relative.parts:
                        continue
                    destination = notice_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    (root / '版本.json').write_text(json.dumps(versions, indent=2), encoding='utf-8')
    (root / '说明.txt').write_text('本包包含 Python 运行库、pyserial、pypdfium2/PDFium、pypdf、Pillow 的运行组件。\n'
                                 '保留随运行组件提供的第三方许可；本包不包含 PyMuPDF/fitz。\n', encoding='utf-8-sig')


def verify_sources(snapshot):
    changed = [name for name, digest in snapshot.items() if sha256(REPO / name) != digest]
    if changed:
        raise RuntimeError('构建期间源文件改变，包未发布：' + ', '.join(changed))


def add_samples(package, samples):
    if samples is None:
        return []
    sys.path.insert(0, str(HOST))
    from score_codec import decode
    names = []
    target = package / '示例曲谱'
    target.mkdir()
    for source in sorted(samples.glob('*.pgl')):
        if not re.fullmatch(r'(?:100\d+|969886)\.pgl', source.name):
            continue
        score = decode(source.read_bytes())
        if 'capacity-' in source.name or score['title'].startswith('Capacity '):
            raise RuntimeError('客户示例不能使用容量测试填充文件。')
        title = re.sub(r'[\\/:*?"<>|]', '_', score['title']).strip().rstrip('.')
        destination = target / (title + '.pgl')
        if destination.exists():
            raise RuntimeError('示例曲谱标题重复：' + title)
        shutil.copy2(source, destination)
        names.append(destination.name)
        portable = source.with_suffix('.pglpack')
        if portable.is_file():
            with zipfile.ZipFile(portable) as archive:
                if archive.testzip() is not None or archive.read('score.pgl') != source.read_bytes():
                    raise RuntimeError('带原谱示例与紧凑曲谱内容不一致：' + portable.name)
                metadata = json.loads(archive.read('source.json'))
                if metadata.get('score_sha256') != sha256(source) or metadata.get('version') != 1:
                    raise RuntimeError('带原谱示例索引不正确：' + portable.name)
                expected = {'score.pgl', 'source.json'} | {page['image_file'] for page in metadata['pages']}
                if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                    raise RuntimeError('带原谱示例包含多余文件：' + portable.name)
                if any(entry.compress_type != zipfile.ZIP_STORED for entry in archive.infolist()):
                    raise RuntimeError('带原谱示例格式不正确：' + portable.name)
                for page in metadata['pages']:
                    if page['image_file'] != 'pages/%d.png' % page['page']:
                        raise RuntimeError('带原谱示例页面路径不正确：' + portable.name)
            packed_destination = destination.with_suffix('.pglpack')
            shutil.copy2(portable, packed_destination)
            names.append(packed_destination.name)
    if not names:
        raise RuntimeError('示例目录没有可验证的 .pgl 文件。')
    return names


def build_upgrader(work, package, firmware, expected_sha):
    """Separate GPL official tool/wrapper; never link it into the main app."""
    if importlib.metadata.version('esptool') != '5.2.0':
        raise RuntimeError('升级器须使用已核对的官方 esptool5.2.0。')
    if sha256(firmware) != expected_sha:
        raise RuntimeError('固件镜像 SHA 与冻结值不同。')
    image_data = firmware.read_bytes()
    if not 24 <= len(image_data) <= 0x140000 or image_data[0] != 0xe9:
        raise RuntimeError('冻结固件尺寸超出应用分区，或 ESP32 镜像格式不正确。')
    tool_work = work / 'upgrade'
    stage = tool_work / 'stage'
    image = stage / 'image'
    image.mkdir(parents=True)
    shutil.copy2(firmware, image / 'firmware.bin')
    image_manifest = dict(chip='esp32', address=0x10000, max_size=0x140000,
                          bytes=len(image_data), sha256=expected_sha)
    (image / 'firmware-manifest.json').write_text(json.dumps(image_manifest, indent=2), encoding='utf-8')
    entry = REPO / 'tools' / 'customer_firmware_upgrade.py'
    shutil.copy2(entry, stage / entry.name)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
               '--name', 'PianoGloveUpgrade', '--distpath', str(tool_work / 'dist'),
               '--workpath', str(tool_work / 'build'), '--specpath', str(tool_work),
               '--collect-all', 'esptool', '--add-data', str(image) + ';image',
               str(stage / entry.name)]
    with (tool_work / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    tool_package = tool_work / 'dist' / 'PianoGloveUpgrade'
    result = subprocess.run([str(tool_package / 'PianoGloveUpgrade.exe'), '--self-test'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8',
                            timeout=90, check=True)
    (tool_work / 'frozen-self-test.json').write_text(result.stdout, encoding='utf-8')
    (tool_work / 'frozen-self-test.stderr.txt').write_text(result.stderr, encoding='utf-8')
    destination = package / '固件升级'
    shutil.copytree(tool_package, destination)
    (destination / '升级器源码').mkdir()
    shutil.copy2(entry, destination / '升级器源码' / entry.name)
    official = destination / '官方工具源码'
    official.mkdir()
    with (tool_work / 'source-download.log').open('w', encoding='utf-8') as log:
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--no-binary=:all:',
                        '--no-build-isolation', 'esptool==5.2.0', '--dest', str(official)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    source_archives = list(official.glob('esptool-5.2.0.tar.gz'))
    if len(source_archives) != 1:
        raise RuntimeError('官方 esptool 对应源码未取得，升级工具不发布。')
    copy_notices(destination, ('esptool', 'bitstring', 'bitarray', 'cryptography', 'pyserial',
                              'reedsolo', 'PyYAML', 'intelhex', 'rich_click', 'click', 'rich',
                              'markdown_it_py', 'mdurl', 'pygments', 'cffi', 'pycparser'))
    (destination / '许可与范围.txt').write_text(
        '本目录的独立升级器按GPL-2.0-or-later提供，对应升级器源码和官方esptool5.2.0源码随附。\n'
        '仅此独立工具链接esptool；主训练程序不导入或链接esptool。\n'
        'firmware.bin是钢琴手套主控已编译应用镜像，非官方工具源码，不包含钢琴手套固件源码。\n'
        '升级器先检查原主板分区并备份NVS，仅写0x10000应用区域，不修改ID/NVS/曲库/分区表。\n'
        '升级记录保存在%LOCALAPPDATA%\\PianoGloveFirmwareUpgrade。\n', encoding='utf-8-sig')
    (package / '04-固件升级.bat').write_bytes(
        b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"\xe5\x9b\xba\xe4\xbb\xb6\xe5\x8d\x87\xe7\xba\xa7\\PianoGloveUpgrade.exe" %*\r\npause\r\n')
    return dict(self_test=json.loads(result.stdout.strip().splitlines()[-1]),
                image=image_manifest, official_source_sha256=sha256(source_archives[0]))


def build(work, output, samples=None, firmware=None, firmware_sha=None, runtime_only=False):
    stage, snapshot = prepare(work)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
               '--name', 'PianoGloveSoftware', '--distpath', str(work / 'dist'), '--workpath', str(work / 'build'),
               '--specpath', str(work), '--paths', str(stage), '--add-data', str(stage / 'web') + ';web',
               '--collect-all', 'pypdfium2', '--copy-metadata', 'pypdfium2', '--copy-metadata', 'pypdf', '--exclude-module', 'fitz',
               '--exclude-module', 'pymupdf', '--hidden-import', 'score_converter_engine',
               str(stage / 'customer_runtime.py')]
    with (work / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    package = work / 'dist' / 'PianoGloveSoftware'
    executable = package / 'PianoGloveSoftware.exe'
    result = subprocess.run([str(executable), '--self-test'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding='utf-8', timeout=90, check=True)
    (work / 'frozen-self-test.json').write_text(result.stdout, encoding='utf-8')
    (work / 'frozen-self-test.stderr.txt').write_text(result.stderr, encoding='utf-8')
    (package / '01-打开软件.bat').write_bytes(b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nPianoGloveSoftware.exe %*\r\nif errorlevel 1 pause\r\n')
    (package / '02-调试和校准.bat').write_bytes(b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nPianoGloveSoftware.exe --debug %*\r\nif errorlevel 1 pause\r\n')
    (package / '03-运行文件自检.bat').write_bytes(b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nPianoGloveSoftware.exe --self-test\r\npause\r\n')
    readme = REPO / 'docs' / '客户软件测试包_启动说明.md'
    shutil.copy2(readme, package / '先读我.md')
    sample_names = add_samples(package, samples)
    copy_notices(package)
    if runtime_only:
        verify_sources(snapshot)
        report = dict(ok=True, runtime_only=True, executable=str(executable), sample_scores=sample_names,
                      serial_opened=False, firmware_included=False, final_zip_written=False,
                      self_test=json.loads(result.stdout.strip().splitlines()[-1]))
        (work / 'runtime-preparation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    upgrade = build_upgrader(work, package, firmware, firmware_sha) if firmware else None
    finalize_package(work, output, package, snapshot,
                     json.loads(result.stdout.strip().splitlines()[-1]), sample_names, upgrade)


def allowed_source(package, path):
    relative = path.relative_to(package).as_posix()
    if relative == '固件升级/升级器源码/customer_firmware_upgrade.py':
        return sha256(path) == sha256(REPO / 'tools' / 'customer_firmware_upgrade.py')
    if relative == '固件升级/第三方固件组件/重链接资料/relink.py':
        return sha256(path) == sha256(REPO / 'tools' / 'relink_customer_firmware.py')
    library_prefix = '固件升级/第三方固件组件/WebServerBinary/'
    if relative.startswith(library_prefix):
        original = REPO / 'firmware' / 'lib' / 'WebServerBinary' / relative[len(library_prefix):]
        if not original.is_file():
            return False
        if sha256(path) == sha256(original):
            return True
        if relative[len(library_prefix):] in ('src/WebServer.cpp', 'src/Parsing.cpp'):
            prefix = '// Local third-party library modifications on 2026-10-10: binary PGL upload,\n' \
                     '// bounded body allocation and empty-preconnect timeout. See PROVENANCE.md.\n'
            return path.read_text(encoding='utf-8') == prefix + original.read_text(encoding='utf-8')
        return False
    # PyInstaller collect-all copies public library modules as data. Permit
    # only these exact directories AND exact hashes of the official installed
    # modules; a renamed customer source file cannot pass this boundary.
    for prefix, dist_name, import_root in [('_internal/pypdfium2/', 'pypdfium2', 'pypdfium2'),
                                           ('固件升级/_internal/esptool/', 'esptool', 'esptool')]:
        if relative.startswith(prefix) and path.suffix.lower() == '.py':
            original = Path(importlib.metadata.distribution(dist_name).locate_file(
                import_root + '/' + relative[len(prefix):]))
            return original.is_file() and sha256(path) == sha256(original)
    return False


def finalize_package(work, output, package, snapshot, runtime_self_test, sample_names, upgrade):
    verify_sources(snapshot)
    forbidden = [path.relative_to(package).as_posix() for path in package.rglob('*')
                 if path.is_file() and path.suffix.lower() in FORBIDDEN_EXTENSIONS
                 and not allowed_source(package, path)]
    if forbidden:
        raise RuntimeError('包中发现不应交付的源/核心资料：' + ', '.join(forbidden))
    manifest = dict(build_date=DATE, edition='customer-software-test', source_snapshot=snapshot,
                    runtime_self_test=runtime_self_test,
                    pyinstaller=importlib.metadata.version('PyInstaller'),
                    os_tested=platform.platform(), other_windows_versions_tested=False,
                    firmware_image_included=upgrade is not None, upgrade=upgrade, customer_sent=False,
                    sample_scores=sample_names,
                    proprietary_application_source_included=False,
                    third_party_firmware_relink=(package / '固件升级' / '第三方固件组件' / '重链接资料' / 'recipe.json').is_file(),
                    files={str(p.relative_to(package)).replace('\\', '/'): sha256(p)
                           for p in package.rglob('*') if p.is_file() and p.name != '运行包清单.json'})
    (package / '运行包清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError('输出压缩包已存在；使用新路径保存，旧包不覆盖。')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                archive.write(path, '钢琴手套软件测试版/' + path.relative_to(package).as_posix())
    # Inspect the delivered ZIP, not just the stage directory.
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP 完整性检查失败')
        for name, digest in manifest['files'].items():
            if hashlib.sha256(archive.read('钢琴手套软件测试版/' + name)).hexdigest() != digest:
                raise RuntimeError('ZIP 文件校验失败：' + name)
    output.with_suffix(output.suffix + '.sha256').write_text(sha256(output) + '  ' + output.name + '\n', encoding='utf-8')
    report = dict(ok=True, package=str(output), package_sha256=sha256(output),
                  package_bytes=output.stat().st_size, files=len(manifest['files']) + 1,
                  self_test=manifest['runtime_self_test'], core_material_found=False, serial_opened=False)
    report['upgrade'] = upgrade
    (work / 'package-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


def resume_package(work, output):
    """Rerun only corrected packaging checks after the already-passing freezes."""
    package = work / 'dist' / 'PianoGloveSoftware'
    snapshot = json.loads((work / 'source-snapshot.json').read_text(encoding='utf-8'))
    runtime = json.loads((work / 'frozen-self-test.json').read_text(encoding='utf-8').strip().splitlines()[-1])
    if not runtime.get('ok') or runtime.get('serial_opened'):
        raise RuntimeError('冻结主程序自检记录缺失或未通过。')
    tool = package / '固件升级'
    upgrade = None
    if tool.exists():
        tested = json.loads((work / 'upgrade' / 'frozen-self-test.json').read_text(encoding='utf-8').strip().splitlines()[-1])
        image = json.loads((tool / '_internal' / 'image' / 'firmware-manifest.json').read_text(encoding='utf-8'))
        if not tested.get('ok') or tested.get('serial_opened') or sha256(tool / '_internal' / 'image' / 'firmware.bin') != image['sha256']:
            raise RuntimeError('独立升级器或镜像验证记录不匹配。')
        official_source = list((tool / '官方工具源码').glob('esptool-5.2.0.tar.gz'))
        if len(official_source) != 1:
            raise RuntimeError('独立升级器对应官方源码未随附。')
        upgrade = dict(self_test=tested, image=image, official_source_sha256=sha256(official_source[0]))
    sample_dir = package / '示例曲谱'
    sample_names = sorted(path.name for path in sample_dir.iterdir()
                          if path.is_file() and path.suffix.lower() in ('.pgl', '.pglpack')) if sample_dir.is_dir() else []
    finalize_package(work, output, package, snapshot, runtime, sample_names, upgrade)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='新的独立构建目录；不覆盖旧目录')
    parser.add_argument('--output', type=Path, required=True, help='新的客户测试 ZIP 文件')
    parser.add_argument('--prepare-only', action='store_true', help='只快照源文件，不编译')
    parser.add_argument('--resume-package', action='store_true', help='已完成冻结自检后，仅重做边界和ZIP验证')
    parser.add_argument('--runtime-only', action='store_true', help='只冻结主EXE和网页，等待最终固件冻结再封包')
    parser.add_argument('--samples', type=Path, help='可选：已复核的实际 .pgl 示例目录；不接收容量填充曲目')
    parser.add_argument('--firmware', type=Path, help='可选：供应方冻结的ESP32编译应用镜像')
    parser.add_argument('--firmware-sha', help='镜像预期 SHA256，必须与 --firmware 一同提供')
    args = parser.parse_args()
    args.work = args.work.resolve()
    args.output = args.output.resolve()
    if bool(args.firmware) != bool(args.firmware_sha):
        parser.error('--firmware 和 --firmware-sha 必须一起提供')
    if args.resume_package:
        resume_package(args.work, args.output)
    elif args.prepare_only:
        stage, snapshot = prepare(args.work)
        print(json.dumps(dict(stage=str(stage), input_files=len(snapshot)), ensure_ascii=False))
    else:
        build(args.work, args.output, args.samples.resolve() if args.samples else None,
              args.firmware.resolve() if args.firmware else None, args.firmware_sha, args.runtime_only)


if __name__ == '__main__':
    main()
