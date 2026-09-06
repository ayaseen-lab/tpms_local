import time

import serial

port = serial.Serial(
    port="COM5",
    baudrate=115200,
    bytesize=8,
    parity="N",
    stopbits=1,
    timeout=2,
)

request = bytes.fromhex("3C 11 00 02 40 01 3E")

port.reset_input_buffer()
port.write(request)
port.flush()

time.sleep(0.2)

response = port.read_all()

print("Received:", response.hex(" ").upper())

port.close()