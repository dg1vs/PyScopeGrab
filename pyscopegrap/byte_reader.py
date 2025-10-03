"""
A read_until method similar to the one in the serial class, which reads until a certain terminator byte is reached or the maximum number of bytes has been read. 

This method reads bytes from the byte array until either the specified terminator is found, the maximum number of bytes has been read, or the end of the byte array is reached. 
The default terminator is the line-feed character (\n, equal to byte 0x0A in hexadecimal), and the default limit for the maximum number of bytes to read is unlimited (None).
There is also an optional size parameter that specifies the maximum number of bytes to be read. If size is None (the default value), there is no maximum number, and the method reads until the terminator is found or the end of the byte array is reached.
self.index is used to track the position of the next byte to be read in the byte array.
"""

class ByteReader:

    timeout = 10
    def __init__(self, file_path):
        self.file_path = file_path
        self.byte_array = self._read_file_to_byte_array()
        self.index = 0

    def _read_file_to_byte_array(self):
        byte_array = bytearray()
        with open(self.file_path, 'r') as file:
            for line in file:
                hex_values = line.strip().split(' ')
                for value in hex_values:
                    byte_array.append(int(value, 16))
        return byte_array

    def write(self, data):
        print('BR: Command', data)

    def read(self, size=1):
        if self.index + size > len(self.byte_array):
            size = len(self.byte_array) - self.index
        bytes_to_return = self.byte_array[self.index:self.index + size]
        self.index += size
        return bytes_to_return

    def read_until(self, terminator=b'\n', size=None):
        read_bytes = bytearray()
        while True:
            if size is not None and len(read_bytes) >= size:
                break
            if self.index >= len(self.byte_array):
                break
            current_byte = self.byte_array[self.index:self.index + 1]
            self.index += 1
            read_bytes += current_byte
            if current_byte == terminator:
                break
        return bytes(read_bytes)

