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


# Um eine read_until-Methode ähnlich der in der serial-Klasse zu implementieren, die liest, bis ein bestimmtes Terminator-Byte erreicht wird oder die maximale Anzahl von Bytes gelesen wurde, können wir die ByteReader-Klasse wie folgt erweitern:
# Diese Methode liest Bytes aus dem Byte-Array, bis entweder der angegebene Terminator gefunden wird, die maximale Anzahl von Bytes gelesen wurde, oder das Ende des Byte-Arrays erreicht ist. Der Standardterminator ist das Line-Feed-Zeichen (\n, entspricht dem Byte 0x0A in Hexadezimal), und die Standardgrenze für die maximale Anzahl zu lesender Bytes ist unbegrenzt (None).
# •	read_until nimmt einen terminator-Parameter an, der das Byte (oder die Byte-Sequenz) spezifiziert, bei dessen Erreichen das Lesen stoppt. Der Standardwert ist b'\n', was dem Newline-Zeichen entspricht.
# •	Es gibt auch einen optionalen size-Parameter, der die maximale Anzahl von Bytes angibt, die gelesen werden sollen. Wenn size None ist (der Standardwert), gibt es keine maximale Anzahl, und die Methode liest, bis der Terminator gefunden wird oder das Ende des Byte-Arrays erreicht ist.
# •	Die Methode liest und sammelt Bytes in read_bytes, bis einer der Abbruchbedingungen erreicht ist: der Terminator gefunden wird, die maximale Anzahl von Bytes gelesen wurde oder das Ende des Byte-Arrays erreicht ist.
# Diese Methode ermöglicht eine flexiblere Kontrolle über den Lesevorgang, ähnlich wie die read_until-Methode in der serial-Kommunikationsbibliothek.
# In dieser Version der Klasse:
# •	self.index wird verwendet, um die Position des nächsten zu lesenden Bytes im Byte-Array zu verfolgen.
# •	Die read-Methode akzeptiert nun ein Argument size, das angibt, wie viele Bytes gelesen werden sollen. Sie gibt ein Byte-Array dieser Größe zurück. Wenn das Ende des Byte-Arrays erreicht ist, wird die tatsächliche Anzahl der verbleibenden Bytes möglicherweise kleiner als angefordert sein.
# •	Die Methode liest die Bytes aus self.byte_array, aktualisiert self.index entsprechend und gibt die gelesenen Bytes zurück.
# Diese Anpassung macht die ByteReader-Klasse flexibler und ähnlicher in der Funktionsweise zu typischen seriellen Kommunikationsbibliotheken, die es erlauben, eine spezifizierte Anzahl von Bytes 
# 
# To implement a read_until method similar to the one in the serial class, which reads until a certain terminator byte is reached or the maximum number of bytes has been read, we can extend the ByteReader class as follows:
# This method reads bytes from the byte array until either the specified terminator is found, the maximum number of bytes has been read, or the end of the byte array is reached. The default terminator is the line-feed character (\n, equal to byte 0x0A in hexadecimal), and the default limit for the maximum number of bytes to read is unlimited (None).
# • read_until adopts a terminator parameter that specifies the byte (or sequence of bytes) at which the read stops. The default value is b'\n', which is the same as the newline character.
# • There is also an optional size parameter that specifies the maximum number of bytes to be read. If size is None (the default value), there is no maximum number, and the method reads until the terminator is found or the end of the byte array is reached.
# • The method reads and collects bytes in read_bytes until one of the termination conditions is reached: the terminator is found, the maximum number of bytes has been read, or the end of the byte array has been reached.
# This method allows for more flexible control over the read process, similar to the read_until method in the Serial Communication Library.
# In this version of the class:
# • self.index is used to track the position of the next byte to be read in the byte array.
# • The read method now accepts a size argument that specifies how many bytes to read. It returns an array of bytes of this size. When the end of the byte array is reached, the actual number of bytes remaining may be less than requested.
# • The method reads the bytes from self.byte_array, updates self.index accordingly, and returns the bytes read.
# This customization makes the ByteReader class more flexible and similar in functionality to typical serial communication libraries that allow a specified number of bytes to be stored. 