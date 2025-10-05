#!/usr/bin/env python3
import pyvisa

def read_binblock(inst):
    # Do not expect a terminator for binary transfers
    prev = inst.read_termination
    inst.read_termination = None

    try:
        # 1) read header: '#' + <ndigits>
        hdr = inst.read_bytes(2)
        if not hdr or hdr[0] != ord('#'):
            raise RuntimeError(f"Expected '#', got {hdr!r}")
        ndigits = int(chr(hdr[1]))
        if ndigits <= 0:
            raise RuntimeError(f"Unsupported binblock (ndigits={ndigits})")

        # 2) read the ASCII length field
        len_str = inst.read_bytes(ndigits).decode("ascii")
        n = int(len_str)

        # 3) read payload
        data = inst.read_bytes(n)

        # 4) (optional) eat one trailing LF if the server sends it
        try:
            inst.timeout = 50  # short peek
            extra = inst.read_bytes(1)
            # if you want to be strict, assert extra == b'\n'
        except Exception:
            pass  # nothing left to read, fine

        return data
    finally:
        inst.read_termination = prev

def main():
    rm = pyvisa.ResourceManager("@py")   # pyvisa-py
    inst = rm.open_resource("TCPIP::127.0.0.1::5025::SOCKET")
    inst.timeout = 15000                 # screenshots can take a few seconds
    inst.write_termination = "\n"
    inst.read_termination  = "\n"

    print("*IDN? ->", inst.query("*IDN?").strip())

    # Request hardcopy and parse the binblock manually
    inst.write("HCOPY:DATA?")
    png_bytes = read_binblock(inst)

    with open("scpi_grab.png", "wb") as f:
        f.write(png_bytes)
    print("HCOPY:DATA? -> scpi_grab.png saved")

if __name__ == "__main__":
    main()
