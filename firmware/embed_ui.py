"""Embed the same offline training UI served by the desktop bridge."""
from pathlib import Path
Import('env')
root = Path(env['PROJECT_DIR'])
phone = root / 'phone-ui'
legacy = (phone / 'manifest.json').is_file()
parts = ['#pragma once\n#include <Arduino.h>\n', f'#define PIANO_GLOVE_LEGACY_PHONE_UI {int(legacy)}\n']
for name, variable in [('software.html','SOFTWARE_HTML'),('software.js','SOFTWARE_JS'),('software.css','SOFTWARE_CSS'),('software-tempo.js','SOFTWARE_TEMPO_JS'),('software-tempo.css','SOFTWARE_TEMPO_CSS'),('software-upload.js','SOFTWARE_UPLOAD_JS'),('software-upload.css','SOFTWARE_UPLOAD_CSS'),('software-audio.js','SOFTWARE_AUDIO_JS'),('software-pack.js','SOFTWARE_PACK_JS'),('software-review.js','SOFTWARE_REVIEW_JS'),('software-review.css','SOFTWARE_REVIEW_CSS')]:
    source = (phone if legacy else root.parent / 'host') / name
    if legacy and not source.is_file():
        continue
    value = source.read_bytes().decode('utf-8')
    assert ')PGLUI"' not in value
    parts.append(f'const char {variable}[] PROGMEM=R"PGLUI({value})PGLUI";\n')
target = root / 'src' / 'software_ui.h'
text = ''.join(parts)
if not target.exists() or target.read_text(encoding='utf-8') != text:
    target.write_text(text,encoding='utf-8')
