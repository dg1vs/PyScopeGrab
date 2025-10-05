
python3 -m pyscopegrap --scpi-server -t /dev/ttyUSB0 --scpi-host 127.0.0.1 --scpi-port 5025 -v



printf "*IDN?\n" | nc 127.0.0.1 5025
printf "MEAS:VOLT:DC?\n" | nc 127.0.0.1 5025
printf "SYST:ERR?\n" | nc 127.0.0.1 5025
printf "CONF:VOLT:DC\n" | nc 127.0.0.1 5025
printf "FOO?\n" | nc 127.0.0.1 5025      # -> -113,"Undefined header"
printf "SYST:ERR?\n" | nc 127.0.0.1 5025  # -> pops the queued -113
