# WebServerBinary

Vendored from Arduino-ESP32 2.0.11 `libraries/WebServer`, used by PlatformIO
framework-arduinoespressif32 3.20011.230801. Original LGPL 2.1-or-later notices
are preserved in each source file.

Upstream: https://github.com/espressif/arduino-esp32/tree/2.0.11/libraries/WebServer

Local changes:

* Preserve embedded NUL bytes in binary PGL uploads using `String(buf, length)`.
* Reject buffered plain request bodies over 16,384 bytes before allocation.
  Larger PGLs use the application-level begin/chunk/commit endpoints (384-byte
  raw chunks). URL-encoded controls and raw bodies are supported; multipart is
  explicitly rejected instead of entering upstream's blocking form parser.
* In `src/WebServer.cpp`, limit an accepted TCP connection with no initial
  request bytes to 150 ms instead of five seconds. This fixes a reproduced
  empty-browser-preconnect delay.
* Parse request/header/body with one absolute 500 ms deadline, capped 2048-byte
  lines and 8192 bytes of headers; delayed bytes do not restart the deadline.
  Preserve embedded NULs and read exactly Content-Length bytes.
* Send through nonblocking `MSG_DONTWAIT`, including response/chunk framing and
  PROGMEM assets. Upstream `WiFiClient::write` has its own select/retry delays
  independent of `setTimeout`; this path therefore does not call it. Stop a
  stalled send after 500 ms with no progress, and cap one whole response at
  2500 ms even if a client trickles progress.
* Call a guarded wait handler on the same Arduino loop at least 20 ms after
  the previous handler returns. The piano firmware services its existing
  feedback/lease/motion state there; it does not recurse into HTTP or parse
  USB commands. This preserves sequential servo traffic during network waits.
  These budgets include cooperative handler execution; they are not hard
  real-time bounds on a motor-bus call or proof of handset reception.
* Avoid RX `flush` after parsing, since the single-request connection is
  closed after its response and a stale zero-byte recv could otherwise spin.

Project firmware uses the local library rather than mutating a toolchain package.
