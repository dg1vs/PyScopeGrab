# scope_grabber.py
from __future__ import annotations

import sys
import time
import logging
from typing import Optional, Tuple

import serial
from PIL import Image, PngImagePlugin


class ScopeGrabber:
    """
    Fluke ScopeMeter 105 grabber (protocol + decoding).
    OS-independent: uses pyserial and Pillow only.

    Usage:
        grab = ScopeGrabber(tty="/dev/ttyUSB0", baud=19200, logger=logging.getLogger(__name__))
        grab.initialize_port()         # open at 1200, request 19200, switch local baud
        grab.get_identity()            # prints identity (like before)
        grab.get_status()               # prints status bits (like before)
        grab.get_screenshot(args)      # reads bytes and saves PNG (like before)
        grab.close()
    """

    def __init__(self, tty: str, baud: int = 19200, *, logger: Optional[logging.Logger] = None):
        self.tty = tty
        self.baud = baud
        self.port: Optional[serial.Serial] = None
        self.LOG = logger or logging.getLogger(__name__)

    # -----------------------
    # Helpers (names kept)
    # -----------------------
    @staticmethod
    def hex2rgb(hexColor: str) -> Tuple[int, int, int]:
        """Convert '#rrggbb' or '0xRRGGBB' to an (R, G, B) tuple.

         Short input (length < 6) is zero-padded per nibble, e.g., 'abc' -> 'a0b0c0'.
         Returns values in range 0..255.
         """

        if hexColor[0] == '#':
            hexColor = hexColor[1:]
        elif hexColor[0:2].lower() == '0x':
            hexColor = hexColor[2:]
        if len(hexColor) < 6:
            hexColor = hexColor[0] + '0' + hexColor[1] + '0' + hexColor[2] + '0'
        return int(hexColor[0:2], 16), int(hexColor[2:4], 16), int(hexColor[4:6], 16)

    @staticmethod
    def display_progress_bar(count, total, suffix=''):
        bar_len = 40
        filled_len = int(round(bar_len * count / float(total)))
        percents = round(100.0 * count / float(total), 1)
        bar = '=' * filled_len + '-' * (bar_len - filled_len)
        sys.stdout.write('[%s] %s%s ...%s\r' % (bar, percents, '%', suffix))

    @staticmethod
    def calculate_checksum(data: bytes) -> int:
        """Device checksum: simple sum of all bytes modulo 256.
        Matches the single trailing CRC byte sent by the ScopeMeter after payload.
        """

        checksum = 0
        for byte in data:
            checksum += byte
            checksum %= 256
        return checksum

    # -----------------------
    # Serial lifecycle
    # -----------------------
    def initialize_port(self, timeout: float = 1.0) -> serial.Serial:
        """Open the serial port and switch the ScopeMeter to higher baud.

        Sequence:
          - Open at 1200 baud (device's default after power-up).
          - Try 'PC 19200' once without timeout handling; on failure, retry strict.
          - Update local 'port.baudrate' to 19200 to match the device.

        Returns:
          Configured pyserial Serial instance.
        """

        import serial  # local import keeps module OS-independent and light
        self.LOG.info('Opening and configuring serial port...')
        self.port = serial.Serial(self.tty, 1200, timeout=timeout)  # device default
        print('done')  # preserving original user feedback

        print(self.baud)
        # Try fast path first (no hard abort), then strict:
        status = self.send_command('PC 19200', timeout=False)
        self.port.baudrate = 19200
        if status is False:
            self.send_command('PC 19200', timeout=True)
        print('done')
        return self.port

    def close(self):
        if self.port and self.port.is_open:
            self.port.close()

    # -----------------------
    # Protocol (names kept)
    # -----------------------
    def send_command(self, command: str, timeout: bool = True):
        """Send ASCII command + CR; parse 2-byte ACK.
        ACK format: <code><CR>
          code '0' : OK
          code '1' : Command syntax error
          code '2' : Command execution error
          code '3' : Synchronization error
          code '4' : Communication error
          other    : Unknown error code

        Args:
          port: pyserial Serial instance
          command: ASCII string without trailing CR
          timeout: If True, abort on missing ACK; if False, return False on timeout

        Returns:
          None on success (code 0), or False when timeout=False and no ACK.
          Exits with error code on known error responses.
        """

        assert self.port is not None, "Port not initialized"
        data = bytearray(command.encode('ascii'))
        data.append(ord('\r'))
        self.port.write(data)
        ack = self.port.read(2)

        if len(ack) != 2:
            if timeout:
                self.LOG.warning('error: command acknowledgement timed out')
                sys.exit(1)
            else:
                return False

        if ack[1] != ord('\r'):
            self.LOG.warning('error: did not receive CR after acknowledgement code')
            sys.exit(1)

        code = int(chr(ack[0]))
        if code == 0:
            return
        elif code == 1:
            self.LOG.warning('error: Command syntax error')
        elif code == 2:
            self.LOG.warning('error: Command execution error')
        elif code == 3:
            self.LOG.warning('error: Synchronization error')
        elif code == 4:
            self.LOG.warning('error: Communication error')
        else:
            self.LOG.warning('error: Unknown error code (' + str(code) + ') in command acknowledgement')
        sys.exit(code)

    def get_identity(self):
        """Query 'ID' and print parsed identity fields.

        The device returns a semicolon-separated ASCII record ending with CR:
          e.g., "ScopeMeter 105 Series II; V7.15; 96-02-06; English V2.15; ..."

        We split into fields and expect exactly 6 entries for the Fluke 105.
        """

        assert self.port is not None, "Port not initialized"
        self.LOG.info('Getting identity of ScopeMeter...')
        self.send_command('ID')
        identity = bytearray()
        while True:
            byte = self.port.read()
            if len(byte) != 1:
                self.LOG.warning('error: timeout while receiving data')
                sys.exit(1)
            if byte[0] == ord('\r'):
                break
            identity.append(byte[0])

        self.LOG.debug(identity)
        identity = identity.split(b';')
        self.LOG.debug(identity)
        if len(identity) != 6:  # 6 is for fluke 105
            self.LOG.warning('error: unable to decode identity strin')
            sys.exit(1)

        model = identity[0].decode()
        firmware = identity[1].decode()
        print('     Model: ' + model)
        print('   Version:' + firmware)

    def get_status(self):
        """Request status ('IS'), decode numeric bitfield, and print set bits.

        Status decoding:
          - Device replies with ASCII digits terminated by CR.
          - Convert to integer and test bits against 'status_text' mapping.
        """

        assert self.port is not None, "Port not initialized"
        status_text = {
            0: 'Hardware settled',
            1: 'Acquisition armed',
            2: 'Acquisition triggered',
            3: 'Acquisition busy',
            4: 'WAVEFORM A memory filled',
            5: 'WAVEFORM B memory filled',
            6: 'WAVEFORM A+/-B memory filled',
            7: 'Math function ready',
            8: 'Numeric results available',
            9: 'Hold mode active',
        }

        self.LOG.info('Getting status of ScopeMeter...')
        self.send_command('IS')
        input_buf = bytearray()
        while True:
            byte = self.port.read()
            if len(byte) != 1:
                self.LOG.warning('error: timeout while receiving data')
                sys.exit(1)
            if byte[0] == ord('\r'):
                break
            input_buf.append(byte[0])
        self.LOG.debug(input_buf)

        ##KI status = int(input_buf)
        status = int(bytes(input_buf).decode("ascii"))
        self.LOG.debug(status)

        for pos, text in status_text.items():
            if status & (1 << pos):
                print(f"Bit {pos} set: {text}")

        return status

    DIGIT0, DIGIT9 = ord('0'), ord('9')

    def wait_for_print_image(self, *, fg: str, bg: str, comment: str):
        assert self.port is not None
        old_timeout = self.port.timeout
        try:
            self.port.timeout = None
            self.LOG.info("Waiting for print stream… press PRINT on the ScopeMeter")
            # sync to 'dddd,'
            digits = bytearray()
            while True:
                x = self.port.read(1)[0]
                if DIGIT0 <= x <= DIGIT9:
                    digits.append(x)
                    if len(digits) > 4:
                        digits.pop(0)
                    continue
                if x == ord(',') and len(digits) == 4:
                    try:
                        n = int(digits.decode('ascii'))
                    except Exception:
                        digits.clear();
                        continue
                    if 1024 <= n <= 65535:
                        payload_len = n
                        break
                    digits.clear()
                else:
                    digits.clear()
            epson = self.port.read(payload_len)
            crc = self.port.read(1)
            if crc:
                dev = crc[0];
                calc = self.calculate_checksum(epson)
                if dev != calc:
                    self.LOG.warning("CRC mismatch: device=%d calc=%d", dev, calc)
            img = self.generate_image(epson, fg=fg, bg=bg)
            img.info.setdefault("png_text", {
                "Generator": "PyScopeGrap V0.1",
                "Description": "Exported from Fluke 105 (PRINT)",
                "Extra text": comment or "",
            })
            return img
        finally:
            self.port.timeout = old_timeout


    def get_screenshot_image(self, *, fg: str, bg: str, comment: str) -> Image.Image:
        """Fetch raw EPSON bytes over serial and return a Pillow Image (no disk I/O)."""
        assert self.port is not None
        print('Downloading screenshot from ScopeMeter...')

        old_timeout = self.port.timeout
        try:
            self.port.timeout = None
            self.send_command('QP')

            # Read header (4 ASCII digits), comma, payload, crc
            ascii_len = self.port.read(4)
            _ = self.port.read(1)  # the comma
            try:
                payload_len = int(ascii_len.decode('ascii'))
            except Exception:
                payload_len = 7454  # fallback to observed size

            if payload_len <= 0 or payload_len > 65535:
                payload_len = 7454

            epson = self.port.read(payload_len)
            ##KI crc_from_device = int.from_bytes(self.port.read(1))
            crc_from_device = self.port.read(1)[0]

            if crc_from_device != self.calculate_checksum(epson):
                self.LOG.warning('CRC-Error')

            # Decode to bitmap
            img = self.generate_image(epson, fg=fg, bg=bg)

            # Stash intended PNG text in a conventional place so callers can use it when saving
            img.info.setdefault("png_text", {
                "Generator": "PyScopeGrap V0.1",
                "Description": "Exported from Fluke 105",
                "Extra text": comment or "",
            })
            return img
        finally:
            self.port.timeout = old_timeout

    # Back-compat shim (optional): same name, but now returns an Image
    def generate_screenshot(self, prn: bytes, opt) -> Image.Image:
        """Deprecated: use generate_image(). Kept for compatibility; returns an Image."""
        return self.generate_image(prn, fg=opt.fg, bg=opt.bg)

    def generate_image(self, prn: bytes, *, fg: str, bg: str) -> Image.Image:
        """Decode EPSON-graphics bytes into a Pillow Image (240×240 RGB)."""
        fg_rgb = self.hex2rgb(fg)
        img = Image.new('RGB', (240, 240), bg)
        pixels = img.load()

        self.LOG.info('%d bytes received', len(prn))
        graphmode = False
        graphlen = 0
        i = 0
        line = 0
        xcoord = 0

        while i < len(prn):
            if not graphmode:
                c = prn[i]
                if c == 0x1b:           # ESC
                    i += 1
                    if prn[i] == 0x2a:  # '*'
                        i += 1          # skip m (unused)
                        i += 1
                        graphlen = prn[i]
                        i += 1
                        graphlen += prn[i] * 256
                        graphmode = True
                        xcoord = 0
                elif c == 0x0d:         # CR → next line group
                    line += 1
                i += 1
            else:
                j = 0
                c = prn[i]
                while j < 8:
                    if c & (1 << j):
                        if (line > 0) and (line < 31) and (((line * 8) - j) < 240):
                            pixels[xcoord, (line * 8) - j] = fg_rgb
                    j += 1
                graphlen -= 1
                if graphlen == 0:
                    graphmode = False
                xcoord += 1
                i += 1

        return img

    # Helper the CLI can use when saving to PNG
    @staticmethod
    def make_pnginfo(img: Image.Image) -> PngImagePlugin.PngInfo:
        pi = PngImagePlugin.PngInfo()
        for k, v in img.info.get("png_text", {}).items():
            pi.add_text(k, v)
        return pi

    # def get_screenshot(self, options):
    #     """Run 'QP' to fetch a screenshot and render it via generate_screenshot().
    #
    #     Transfer layout (as implemented here):
    #       1) Read 4 ASCII digits: total payload length (not yet used).
    #       2) Read one byte ',' separator.
    #       3) Read 7454 bytes of EPSON graphics (empirical for 240×240).
    #       4) Read one-byte CRC from device and compare to local checksum.
    #
    #     Notes:
    #       - Temporarily disables 'port.timeout' to allow full blocking reads.
    #       - On CRC mismatch, logs a warning but continues to save the image.
    #     """
    #
    #     assert self.port is not None, "Port not initialized"
    #     print('Downloading screenshot from ScopeMeter...')
    #
    #     old_timeout = self.port.timeout
    #     self.port.timeout = None
    #
    #     self.send_command('QP')
    #
    #     self.LOG.debug('# Read length')
    #     ascii_chars = self.port.read(4)
    #     ascii_string = str(ascii_chars)
    #     payload_len = int(ascii_chars.decode("ascii"))
    #     # 7454: observed payload size for 240x240 EPSON graphics on Fluke 105.
    #
    #     self.LOG.debug(ascii_chars)
    #     self.LOG.debug(payload_len)
    #
    #     self.LOG.debug('# Read ,')
    #     self.LOG.debug(self.port.read(1))
    #
    #     self.LOG.debug('# Read data')
    #     epson = self.port.read(payload_len)
    #     self.LOG.debug(epson)
    #     self.LOG.debug(len(epson))
    #
    #     self.LOG.debug('# Read CRC')
    #     crc_from_device = int.from_bytes(self.port.read(1))
    #     self.LOG.debug(crc_from_device)
    #     crc_calculated = self.calculate_checksum(epson)
    #     self.LOG.debug(crc_calculated)
    #
    #     if crc_from_device != crc_calculated:
    #         self.LOG.warning('CRC-Error')
    #
    #     self.port.timeout = old_timeout
    #
    #     self.generate_screenshot(epson, options)
    #
    # # -----------------------
    # # Image creation (names kept)
    # # -----------------------
    # def generate_screenshot_test(self, opt):
    #     """Create a synthetic 240×240 test image (same drawing as before)."""
    #     fg = self.hex2rgb(opt.fg)
    #     # NOTE: keep original reliance on opt.bg / opt.auto / opt.out for now
    #     img = Image.new('RGB', (240, 240), opt.bg)
    #     pixels = img.load()
    #
    #     for i in range(240):
    #         pixels[i, i] = fg
    #         pixels[i, 119] = fg
    #         pixels[119, i] = fg
    #         pixels[239 - i, i] = fg
    #
    #     if opt.out is None:
    #         self.LOG.debug('file will be saved in current directory')
    #         opt.out = 'screenshot_' + str(int(time.time())) + '.png'
    #     img.save(opt.out)
    #     self.LOG.debug(opt.out + ' saved')
    #     if opt.auto:
    #         img.show()
    #
    # def generate_screenshot(self, prn: bytes, opt):
    #     """Decode EPSON-graphics bytes into a 240×240 PNG (same pixel logic)."""
    #     fg = self.hex2rgb(opt.fg)
    #     img = Image.new('RGB', (240, 240), opt.bg)
    #     pixels = img.load()
    #
    #     png_info = PngImagePlugin.PngInfo()
    #     png_info.add_text('Generator', 'PyScopeGrap V0.1')
    #     png_info.add_text('Description', 'Exported from Fluke 105')
    #     png_info.add_text('Extra text', opt.comment)
    #
    #     self.LOG.info(str(len(prn)) + ' bytes received')
    #     graphmode = False
    #     graphlen = 0
    #     i = 0
    #     line = 0
    #     xcoord = 0
    #
    #     while i < len(prn):
    #         if not graphmode:
    #             c = prn[i]
    #             if c == 0x1b:
    #                 i += 1
    #                 if prn[i] == 0x2a:  # *
    #                     i += 1
    #                     i += 1
    #                     graphlen = prn[i]
    #                     i += 1
    #                     graphlen += prn[i] * 256
    #                     graphmode = True
    #                     xcoord = 0
    #             elif c == 0x0d:
    #                 line += 1
    #             i += 1
    #         else:
    #             j = 0
    #             c = prn[i]
    #             while j < 8:
    #                 if c & (1 << j):
    #                     if (line > 0) and (line < 31) and (((line * 8) - j) < 240):
    #                         pixels[xcoord, ((line) * 8) - j] = fg
    #                 j += 1
    #             graphlen -= 1
    #             if graphlen == 0:
    #                 graphmode = False
    #             xcoord += 1
    #             i += 1
    #
    #     if opt.out is None:
    #         self.LOG.debug('file will be saved in current directory')
    #         opt.out = 'screenshot_' + str(int(time.time())) + '.png'
    #     img.save(opt.out, 'PNG', pnginfo=png_info)
    #
    #     print(opt.out + ' saved')
    #     if opt.auto:
    #         img.show()
