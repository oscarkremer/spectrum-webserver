import socket
import json
import time

class SpectrumClient:
    def __init__(self, host_ip: str, port: int = 65432):
        self.host_ip = host_ip
        self.port = port

    def send_command(self, payload: dict) -> dict:
        """Sends a JSON command to the Linux Spectrum daemon and returns the response."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)  # 3-second connection timeout
                s.connect((self.host_ip, self.port))
                s.sendall(json.dumps(payload).encode('utf-8'))
                
                data = s.recv(4096).decode('utf-8')
                return json.loads(data)
        except Exception as e:
            return {"status": "ERROR", "msg": f"Failed to connect to daemon: {str(e)}"}

    def set_oscillator(self, amplitude: float, freq_hz: float):
        return self.send_command({"cmd": "set_oscillator", "amp": amplitude, "freq": freq_hz})

    def set_hr(self, freq_default: float, freq_heating: float, duration: float):
        return self.send_command({"cmd": "run_sequence_hr", "freq_default": freq_default, "freq_heating": freq_heating, "duration": duration})

    def set_amplification(self, freq_default: float, freq_heating: float, duration: float):
        return self.send_command({"cmd": "run_sequence_hr", "freq_default": freq_default, "freq_heating": freq_heating, "duration": duration})


# --- Example Usage ---
if __name__ == "__main__":
    # Replace with your Linux PC's local IP address
    LINUX_HOST_IP = "10.144.56.156" 

    client = SpectrumClient(LINUX_HOST_IP)

    # 1. Test Connection
    res_oscillator = client.set_oscillator(amplitude=0.3, freq_hz=80_000_000)
    # 2. Modify Core 0 Frequency to 125 MHz
#    for i in range(10):
#        res_freq = client.set_hr(freq_default=80_000_000, freq_heating=70_000_000, duration=0.1)
#        time.sleep(1)
    #print("Frequency Update:", res_freq)


