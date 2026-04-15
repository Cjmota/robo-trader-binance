import threading

class PortfolioManager:
    def __init__(self, max_positions=3):
        self.max_positions = max_positions
        self.open_positions = 0
        self.lock = threading.Lock()

    def can_open(self):
        with self.lock:
            return self.open_positions < self.max_positions

    def register_open(self):
        with self.lock:
            if self.open_positions < self.max_positions:
                self.open_positions += 1

    def register_close(self):
        with self.lock:
            if self.open_positions > 0:
                self.open_positions -= 1
                
    def get_status(self):
        with self.lock:
            return self.open_positions, self.max_positions