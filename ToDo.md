- baud rate macht hier keinen Sinn. Es ist fix auf 1200 eingestellt. Und muss auch so bleiben
- Remove or wire up display_progress_bar() It’s defined but unused; either delete it or call it during the long read(payload_len) loop (switch to chunked reads to get progress). File: scope_grabber.py
- -g/-w doesn't work

- Replace sys.exit() in library code with exceptions Inside scope_grabber.py, raise custom exceptions (e.g., ScopeProtocolError) instead of exiting the interpreter. Let the CLI (PyScopeGrap.py) and GUI catch and present errors. file: scope_grabber.py
- Make length parsing more defensive In get_screenshot_image(), if the 4 ASCII digits aren’t digits, you fallback to 7454. Consider validating the comma separator and logging the raw header for future decoding tweaks. 
- Use chunked reads for large payloads Serial.read(N) may return fewer bytes; loop until you collect N, with an overall timeout, and optionally update a progress callback (GUI could display it in the status bar).  




