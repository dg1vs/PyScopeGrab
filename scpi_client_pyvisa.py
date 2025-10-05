#!/usr/bin/env python3
import pyvisa

def main():
    rm = pyvisa.ResourceManager("@py")  # or default RM
    inst = rm.open_resource("TCPIP::127.0.0.1::5025::SOCKET")
    inst.timeout = 10000
    inst.write_termination = "\n"
    inst.read_termination  = "\n"

    print("*IDN? ->", inst.query("*IDN?").strip())

    # Robust option: disable read_termination just for the binary query
    prev = inst.read_termination
    inst.read_termination = None
    #png_bytes = inst.query_binary_values("HCOPY:DATA?", datatype="B", container=bytes)
    png_bytes = inst.query_binary_values(
        "HCOPY:DATA?",
        datatype="B",
        container=bytes,
        expect_termination=False  # <-- key line
    )


    with open("scpi_grab.png", "wb") as f:
        f.write(png_bytes)
    print("HCOPY:DATA? -> scpi_grab.png saved")

if __name__ == "__main__":
    main()
