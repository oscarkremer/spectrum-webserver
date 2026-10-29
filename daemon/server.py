import socket
import json
import logging
import signal
import sys
from time import monotonic, sleep
import spcm

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

HOST = '0.0.0.0'  # Listen on all network interfaces
PORT = 65432      # Port for TCP client requests
ADDRESS = "TCPIP::10.144.56.93::inst0::INSTR"

class SpectrumDaemon:
    def __init__(self, device_address):
        self.device_path = device_address
        self.card = None
        self.is_running = True

    def initialize_card(self):
        logging.info(f"Opening Spectrum Card handle: {self.device_path}...")
        self.card = spcm.Card(self.device_path)
        self.card.open()
        
        # Configure initial DDS setup (adjust channels/clocks as needed)
        # Start execution loop once during boot
        self.card.card_mode(spcm.SPC_REP_STD_DDS)
        self.card.set_i(spcm.SPC_CHENABLE, spcm.CHANNEL0 | spcm.CHANNEL1 | spcm.CHANNEL2 | spcm.CHANNEL3)
        self.card.set_i(spcm.SPC_AMP0, 1000)
        self.card.set_i(spcm.SPC_AMP1, 1000)
        self.card.set_i(spcm.SPC_AMP2, 1000)
        self.card.set_i(spcm.SPC_ENABLEOUT0, 1)
        self.card.set_i(spcm.SPC_ENABLEOUT1, 1)
        self.card.set_i(spcm.SPC_ENABLEOUT2, 1)
        self.card.set_i(spcm.SPC_CLOCKMODE, spcm.SPC_CM_INTPLL)
        self.card.set_i(spcm.SPC_TRIG_ORMASK, spcm.SPC_TMASK_NONE)
        self.card.set_i(spcm.SPC_TRIG_ANDMASK, spcm.SPC_TMASK_NONE)
        self.dds = spcm.DDS(self.card)
        self.dds.reset()
        self.dds.data_transfer_mode(spcm.SPCM_DDS_DTM_SINGLE)
        self.card.set_i(spcm.SPC_DDS_CORES_ON_CH0, spcm.SPCM_DDS_CORE0)
        self.card.set_i(spcm.SPC_DDS_CORES_ON_CH1, spcm.SPCM_DDS_CORE47)
        self.card.set_i(spcm.SPC_DDS_CORES_ON_CH2, spcm.SPCM_DDS_CORE48)
        self.card.start(spcm.M2CMD_CARD_ENABLETRIGGER)
        self.dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
        self.dds[0].amp(0.2)
        self.dds[0].freq(80e6)
        self.dds[47].freq(0)
        self.dds[47].phase(90)
        self.dds[47].amp(0.0)
        self.dds[48].freq(0)
        self.dds[48].phase(90)
        self.dds[48].amp(0.0)
        self.dds.exec_at_trg()
        self.dds.write_to_card()
        self.card.cmd(spcm.M2CMD_CARD_FORCETRIGGER)
        logging.info("Spectrum Card active and generating signals continuously.")

    def process_command(self, payload):
        """Processes dynamic commands without re-opening or resetting the card handle."""
        cmd_type = payload.get('cmd')
        
        if cmd_type == 'set_oscillator':
            amp_oscillator = payload.get('amp')
            freq_oscillator = payload.get('freq')
            target = self.dds.trg_count() + 2  # Expecting one  trigger for this command
            self.dds[0].amp(float(amp_oscillator))
            self.dds[0].freq(float(freq_oscillator))
            self.dds.exec_at_trg()
            self.dds.write_to_card() 
            self.card.cmd(spcm.M2CMD_CARD_FORCETRIGGER)   
            # Calculate core register offset (0x10 per core)
            deadline = monotonic() + 5
            while self.dds.trg_count() < target:
                if monotonic() > deadline:
                    return {"status": "ERROR", "msg": "Timeout waiting for trigger count."}
                sleep(0.01)
            return {"status": "OK", "msg": f"Amplitude {amp_oscillator} frequency set to {freq_oscillator} Hz"}

        elif cmd_type == 'run_sequence_hr':
            freq_default = payload.get('freq_default')
            freq_heating = payload.get('freq_heating')
            duration = payload.get('duration')

            assert self.card and not (self.card.status() & spcm.M2STAT_CARD_READY)
            target = self.dds.trg_count() + 2
            self.dds[0].freq(float(freq_heating))
            self.dds[47].amp(1)                      # ch1 DC on: 0.2 × 1000 mV = 200 mV
            self.dds.trg_timer(float(duration))                    # 100 ms
            self.dds.trg_src(spcm.SPCM_DDS_TRG_SRC_TIMER)
            self.dds.exec_at_trg()
            self.dds[0].freq(float(freq_default))
            self.dds[47].amp(0.0)                      # ch1 DC off
            self.dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
            self.dds.exec_at_trg()
            self.dds.write_to_card()
            self.card.cmd(spcm.M2CMD_CARD_FORCETRIGGER)
            deadline = monotonic() + 5
            while self.dds.trg_count() < target:
                if monotonic() > deadline:
                    return {"status": "ERROR", "msg": "Timeout waiting for trigger count."}
                sleep(0.01)
            return {"status": "OK", "msg": f"Amplitude {amp_oscillator} frequency set to {freq_oscillator} Hz"}

        elif cmd_type == 'run_sequence_amplificatoin':
            core = payload.get('core', 0)
            phase_deg = payload.get('phase')
            reg_offset = spcm.SPC_DDS_CORE0_PHASE + (core * 0x10)
            self.card.set_param(reg_offset, phase_deg)
            self.card.set_param(spcm.SPC_DDS_CMD, spcm.SPCM_DDS_CMD_EXEC_NOW)
            return {"status": "OK", "msg": f"Core {core} phase set to {phase_deg} deg"}

        elif cmd_type == 'ping':
            return {"status": "OK", "msg": "Spectrum Card Daemon active"}

        else:
            return {"status": "ERROR", "msg": f"Unknown command: {cmd_type}"}

    def run_server(self):
        self.initialize_card()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        server_socket.settimeout(1.0)  # Non-blocking timeout for clean exit

        logging.info(f"Command listener active on TCP port {PORT}...")

        while self.is_running:
            try:
                conn, addr = server_socket.accept()
            except socket.timeout:
                continue

            try:
                data = conn.recv(4096).decode('utf-8')
                if data:
                    payload = json.loads(data)
                    logging.info(f"Request from {addr[0]}: {payload}")
                    response = self.process_command(payload)
                    conn.sendall(json.dumps(response).encode('utf-8'))
            except Exception as e:
                logging.error(f"Error handling request: {e}")
                err_resp = {"status": "ERROR", "msg": str(e)}
                conn.sendall(json.dumps(err_resp).encode('utf-8'))
            finally:
                conn.close()

        # Clean shutdown only when explicit stop command or signal is received
        logging.info("Shutting down daemon and releasing Spectrum handle...")
        self.card.close()
        server_socket.close()

if __name__ == '__main__':
    daemon = SpectrumDaemon(ADDRESS)

    def handle_signal(sig, frame):
        logging.info("Termination signal received.")
        daemon.is_running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    daemon.run_server()