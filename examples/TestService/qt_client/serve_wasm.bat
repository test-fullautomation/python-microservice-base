@echo off
:: Serve the WASM build with COOP/COEP headers required for multi-threaded
:: WASM (SharedArrayBuffer).  Plain `python -m http.server` will NOT work —
:: it serves the files but the WASM module hangs at startup because Qt's
:: threading bootstrap can't allocate a SharedArrayBuffer.
::
:: Override the port:   set PORT=9000 ^&^& serve_wasm.bat
python "%~dp0serve_wasm.py" "%~dp0build-wasm"
