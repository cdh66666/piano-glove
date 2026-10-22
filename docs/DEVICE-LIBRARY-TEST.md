# Device software library and hotspot

> Publication note: This is a historical validation record. Original device logs, Flash backups and local validation artifacts are retained locally and are not bundled with this repository. Artifact names below are trace identifiers, not download links; test dates, results and unverified items remain as originally recorded.

Firmware keeps the established two-servo-model calibration and fixed direction
mapping. Piano fingers 1..5 drive physical IDs 2..6; ID 1 holds its working
lifted endpoint during both training and songs. The saved midpoint is for idle
calibration/reference use, not the playing pose.
No enrollment or ID changes are introduced by this software module.

## Implemented protocol

`INFO` adds `software_protocol=1`, real `ap`, `ip`, and `ap_ready` values.
Firmware version remains 2.2.4; capability, source and build hashes distinguish
this extension from the earlier firmware with a hard-coded AP name.

USB commands (newline-terminated at 115200):

* `LIB INFO` — capacity, occupied count, `chunk_max=384`, current `upload_owner`,
  `score_clock=continuous-v1` and `calibration_advisory=1`.
* `LIB LIST` — `LIB_ITEM slot=... bytes=... stored=... notes=... duration_ms=... title_hex=...`, terminal `OK LIB LIST count=...`.
* `LIB BEGIN slot bytes`, `LIB CHUNK hex`, `LIB COMMIT`, `LIB ABORT` — upload canonical PGL1, up to 384 binary bytes per chunk. Both receive and tokenizer buffers are 1024 bytes.
* `LIB READ slot` — canonical original bytes in `LIB_DATA hex=...` lines, terminal `OK LIB READ`.
* `LIB DELETE slot` — delete one occupied slot.
* `LIB PLAY slot tempo_pct amplitude_pct [hold_pct]` — explicit score playback.
* `LIB TRAIN mask hold_pct amplitude_pct` — finger bits 0..4 map to IDs 2..6.
* `LIB PATTERN pattern repeats rate amplitude_pct hold_pct` — one command starts
  a device-local sequence: pattern 0 single, 1 combinations, 2 alternating;
  repeats 1..20; rate 50..1000 percent, or 0 for feedback-paced fastest training.
* `LIB TEMPO tempo_pct` — change live tempo without jumping score time.
* `LIB STATE` — `LIB_STATE <JSON>` then `OK LIB STATE`.
  USB uses compact v1 numeric flags and six nine-column feedback rows; the
  desktop bridge expands this to the same full structure as hotspot HTTP.
  `m=2` means pattern mode; `pt/ps/pc/pf` report pattern, zero-based phase,
  total phases and fastest flag. `er` is the detected encoder endpoint;
  `b` has six `[min,max,slack,calibration_valid]` rows.
  `ct=1` and `ca=1` advertise continuous score timing and advisory calibration.
  Expanded USB and hotspot state expose `score_clock="continuous-v1"` and
  `calibration_advisory=true`. `cp=0/cl=-1` (expanded `false/null`) mean no
  arrival barrier. `si` counts onsets whose bounded targets were submitted;
  `sn` is the file's total note count. These are command/timeline counters,
  not proof that a finger reached its goal. Completion/STOP retains them
  until the next score starts.
* `LIB KEEP` — renew the USB owner's 2-second lease.
* `LIB STOP` — cancel playback/holding, disable torque, restore temporary STS torque limits.
* `LIB TEST OFFHAND` / `LIB TEST NORMAL` — explicit USB-only temporary bare-hand
  bench mode; switching first stops/SAFE, is not saved, and boot defaults NORMAL.

Hotspot: real MAC-based `PIANO_GLOVE_xxxxxx`, open network (no password), IP
192.168.4.1. The same offline `host/software.html`, JS and CSS are embedded by
`firmware/embed_ui.py`; phone operation needs no running desktop bridge.
Repeated score taps may lift the repeated finger to its calibrated release endpoint,
clipped to hardware travel. Normal press depth and training targets stay unchanged.
DHCP advertises the glove DNS server. The bounded DNS responder accepts EDNS
queries and resolves A queries to the glove, while AAAA/HTTPS return NODATA.
Android/vendor, Apple and Windows connectivity-check routes and unknown HTTP
probe paths redirect to the offline control page. Select the glove hotspot in
the phone Wi-Fi list; the system opens its network-login page or shows a login
notification. On 2026-10-11 the user's Honor-family phone opened the control
page directly without manually opening a browser or typing an address. Other
brands have protocol coverage, but their actual system popup is not yet tested.
The HTTP fallback does not intercept TLS or install certificates.

The desktop converter exports `.pglpack` when a genuine PDF preview exists.
It contains the unchanged PGL plus source-page PNGs and a SHA-bound note index.
Importing in the phone browser stores the original pages locally and uploads
only the compact PGL to the glove. The glove's 100-song capacity therefore does
not include original-page images; use the same phone browser to retain them.

HTTP routes:

* GET `/api/library`, `/api/state`, `/api/score?slot=N` (score JSON),
  `/api/download?slot=N` (original binary PGL).
* POST `/api/upload?slot=N`, content type `application/octet-stream`.
* POST `/api/play`, form fields slot, tempo, amplitude, hold.
* POST `/api/train`, form fields mask, hold, amplitude.
* POST `/api/pattern`, form fields pattern, repeats, tempo, amplitude, hold.
* POST `/api/tempo` (tempo), `/api/delete` (slot), `/api/keep`, `/api/stop`.

USB and Wi-Fi leases are separate: USB KEEP cannot keep Wi-Fi movement alive
and vice versa. Loss of the controller stops torque; reconnect never resumes
an old motion. Reading/downloading complete scores is rejected while moving.
An active upload blocks PLAY/TRAIN preparation. BEGIN/CHUNK/COMMIT/ABORT from
the other transport cannot cancel or consume an existing upload transaction.

## Storage and integrity

100 numbered slots use the existing default SPIFFS partition; no repartition
or NVS erasure is required. Each upload uses a temporary original PGL, validates
its version/length/CRC32/event order/finger overlap, then losslessly compresses
each event: delta-start varint, duration varint, four pitch/finger/velocity/
amplitude bytes. The original 128-byte header and checksum are retained.
Reconstructed data is CRC-checked before replacement and again on boot/play.

Replacement preserves a `.bak` until the new compressed file passes readback
CRC. Boot restores a valid backup when the new target is missing or corrupt.
Invalid files are not added to the in-memory metadata cache. Normal INFO/LIST
does not repeatedly scan 100 SPIFFS paths. Compression writes in 1024-byte
blocks, and compressed reads use 1024-byte buffers.
Mount failure never silently wipes an existing library. Firmware initializes
only a SPIFFS partition whose complete raw flash is still erased (all 0xFF).
Any nonblank or unreadable partition is preserved with `ready=false` and
`storage_mount_failed_preserved` until repaired explicitly.

The count limit of 100 does not promise 100 arbitrary-length pieces. Actual
capacity depends on note count and timings; metadata reports remaining bytes
and rejects full storage instead of discarding an existing piece. Uploads
need temporary raw plus compressed space. USB supports up to 60,000 events;
the Arduino HTTP plain-body path is explicitly limited to 65,536 bytes before
allocation (about 4,088 PGL events). Larger files currently use USB chunks.

The local LGPL `WebServerBinary` fork fixes the Arduino 2.0.11 plain binary
body NUL truncation bug; original notices and provenance are retained.
It also limits a TCP preconnect with no first request byte to 150 ms, while
leaving upload/body parsing timeouts unchanged. A real hotspot test reproduced
the upstream single-client queue blocking a second STATE request for 5.072 s;
the post-fix latency is checked separately in the on-device evidence.

## Training and movement

Targets use the central 90% stroke for STS, existing SC09 inset, model-specific
fixed press direction, and one synchronized write. Speed uses verified bench
normalization (SC09 1000 / STS 8000 counts/s), not the ordinary SC09 200 cap.
LIB target direction explicitly follows the fixed model table, independent of
stored `slot.dir`: both model versions' IDs 1..6 press toward minimum.
The STS ID2 direction was corrected after direct feedback on 2026-10-11.
Calibrated min/mid/max, persisted
direction settings and the legacy ARM path are not rewritten. STATE exposes
`direction_source=fixed_model`, `press_directions`, `piano_ids=[2,3,4,5,6]`,
`thumb_pose_id=1`, and actual per-axis targets.
Software score and training initialization uses the scoped
`armLibrarySoftwarePose` entry. The released musical pose is verified against
fresh hardware bounds and goal/torque readback. After arming, the score clock
and first six-axis musical broadcast begin together at the checked library
speed with acceleration 0. No intermediate midpoint or range-recovery
pose is added. Moving valid feedback and positions beyond the recorded
calibration plus 15% do not block this software entry. Missing calibration,
invalid hardware frames, bad goal/torque readback and temperature/voltage faults
still prevent arming. The general ARM/PREPARE and benchmark policies are
unchanged; calibration data is not overwritten.

Recorded calibration ranges and their slack are display references. Excursions
produce frontend hints only. Software targets still remain at least 5% inside
each calibrated endpoint and inside the freshly read hardware-limit
intersection; an empty target intersection fails before a command is sent.
OFFHAND/NORMAL remains nonpersistent test metadata, but software calibration
excursions need no special recovery mode. Hardware-limit excursions, lost
position/health frames, temperature/voltage faults, controller lease loss and
explicit STOP still stop output.

Song time advances continuously at the requested tempo, independently of
measured position, movement direction, half-target progress or final arrival.
All onsets and releases use original score timestamps. For adjacent notes on
the same finger, a scheduled lift occupies at most 40 wall milliseconds and at
most half the preceding available interval, before the next canonical onset.
If a delayed loop already missed that lift window, it advances immediately
without inserting an extra wait. The musical audio timeline is not shortened
by this mechanical pre-release. Feedback remains available for position
visualization and holding-output control.

Pattern training no longer waits for an HTTP round trip between each phase.
Every phase uses the existing calibrated amplitude and maximum verified servo
speed. For axes whose targets changed, the phase arrival tolerance is the
smaller of 114 STS / 35 SC09 counts and half the actual requested movement
(minimum one count). A small 20% movement cannot count as arrived while still
stationary just because it fits inside the ordinary arrival allowance. Full
strokes retain the established 114/35-count threshold; unchanged axes do not
receive an extra precision requirement. Initial preparation uses the ordinary
114/35-count tolerance rather than demanding half of a remaining one- or
two-count adjustment inside a servo dead zone. The changed-axis mask is reset
for each commanded phase. Rate 0 adds no timed dwell once that
fresh feedback confirms arrival; normal rates retain their requested dwell as
a minimum. Failure to arrive within 1.8 seconds stops with an explicit error.
This is a hardware-paced training mode, not a new claimed servo frequency.
Scores support 50..1000% requested time scaling and no rate 0. Tempo changes
integrate the old rate up to the change instant; they do not rewind song time.
A requested rate does not establish that the physical mechanism can execute
every note at that speed. Full STATE reports an unpaused continuous clock, so
browser audio follows the canonical score instead of arrival barriers.
At duration, firmware submits the final lifted goals and immediately releases
torque without waiting for arrival. Exactly one `LIB_SCORE_COMPLETE` record
states `timeline_complete=true` and `arrival_checked=false`; this is musical
completion evidence, not a claim of successful physical final return.

Idle STATE requests perform a real synchronized position read without enabling
torque or sending any goal. A read failure marks position invalid and retains
the last actual sample timestamp. While library motion is running, STATE uses
the existing 20 ms frames; it does not perform a second competing read. Busy
legacy calibration/motion leaves idle position invalid rather than publishing
an old sample as live. HTTP feedback carries each axis's measured calibration
min/max, min/max plus unchanged slack, and calibration validity.

Native tests `test_library_pattern.py` and `test_library_hold_state.py` execute
the actual phase policy, extracted idle-read function and compact serializer.
They verify no advancement before feedback, fastest versus scaled timing,
counter wrap, parameter bounds, both model schemas, and invalidation of failed
idle reads. These checks do not establish physical frequency; flashing and
live measurement are separate root-task work.

`test_library_score_clock.py` executes the actual C++ start, sendPose,
serviceMotion and score scheduler functions with fake hardware I/O. Four
original-PDF PGL excerpts and one synthetic feature fixture run across both
models, 50/100/200/1000% rates and stalled/lagging feedback: 80 cases finish at
the requested deadline within the 5 ms simulated tick. Tests cover advisory
calibration, same-finger pre-release and missed windows, rests/chords, live
tempo, bounded/clipped targets, the initial six-axis library-speed broadcast,
no final-arrival wait, and retained hardware/health/communications/lease/STOP
faults. Pattern arrival pacing remains separately checked. These native
checks are not physical or acoustic acceptance; application flashing and
real-device verification are recorded separately.
STATE preserves `last_stop_reason` and `last_stop_at_ms` when a later temporary
error occurs. `last_prepare_ms` and `last_pose_ms` help separate initialization
time from network delay; actual movement stops emit `LIB_STOP` to serial.
Position feedback uses a complete six-axis frame on a nominal 20 ms schedule,
separate from one-axis health polling every 100 ms. Both transports report
sample age, sample timestamp, position validity and health age/validity;
unread health fields are never interpreted as a real zero-voltage measurement.
A failed complete position frame invalidates it and stops, rather than
presenting an old position as fresh. Actual cadence depends on communication
and is checked in the hardware reports. The compact USB fixture measures
384 bytes, replacing the roughly 2 KB full JSON that blocked the 115200 link.

STS variable holding uses RAM address 48, readback verification, the preexisting
limit as the maximum, and restoration after stopping. This is a motor output
limit, not a calibrated human-finger force sensor. SC09 address 48 is instead
the EPROM lock flag, so this firmware does **not** write STS torque-limit bytes
to SC09. SC09 currently supports hold 0 (release) or 100 (position hold), not
continuous resistance percentages. No EEPROM torque parameter is modified.
An axis keeps its original output limit while moving in either direction.
The selected lower static hold limit (or torque-off at hold 0) is applied
only after a fresh position frame confirms the target within 114 STS / 35
SC09 counts. The looser half-stroke progression rule does not trigger static
power reduction. This distinguishes movement from maintaining an arrived pose.

Primary register references:

* https://docs.waveshare.net/Memory_Map_Explanation/SC_Servo_Memory_Map_Explanation/
* https://github.com/ftservo/FTServo_Arduino/blob/main/src/SCSCL.h
* https://www.feetechrc.com/Data/feetechrc/upload/file/20220618/先看这里-入手教程2-1.pdf

## Evidence boundary

Firmware builds successfully under pinned ESP32 Arduino 2.0.11 / PlatformIO
espressif32 6.4.0. The independent native C++ review executes the real
`score_format.h` against actual generated PGLs and checks byte-exact
compression round trips, truncated packed events, CRC corruption and varint
overflow. Build/native checks do not substitute for on-device capacity,
power-cycle retention, hardware motion or an actual phone/browser test.
`firmware/tests/test_library_upload_guards.py` compiles and executes the actual
C++ guard prefixes: cross-transport BEGIN fails before aborting, ownership
checks reject the other transport, active or slot-only incomplete uploads
block movement preparation, and bounds/busy failures do not mutate the upload.

On-device results are recorded by the parent task under
`local validation record: software-20261010`; use those timestamped reports for proven capacity
and actual hardware behavior. Do not treat this implementation description as
a completed 100-song, mobile or wearing acceptance test.
