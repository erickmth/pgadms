import time
import threading
import keyboard
from pynput.mouse import Controller, Button

class AutoClicker:
    def __init__(self):
        self.mouse = Controller()
        self.clicking = False
        self.delay = 0.1  # Intervalo entre cliques em segundos
        self.start_stop_key = 'ctrl+l'
        
    def start_clicking(self):
        self.clicking = True
        print("AutoClicker iniciado!")
        while self.clicking:
            self.mouse.click(Button.left)
            time.sleep(self.delay)
    
    def stop_clicking(self):
        self.clicking = False
        print("AutoClicker parado!")
    
    def toggle_clicking(self):
        if self.clicking:
            self.stop_clicking()
        else:
            # Espera 3 segundos antes de iniciar
            print("Aguardando 3 segundos antes de iniciar...")
            time.sleep(3)
            threading.Thread(target=self.start_clicking, daemon=True).start()
    
    def run(self):
        keyboard.add_hotkey(self.start_stop_key, self.toggle_clicking)
        print(f"Pressione {self.start_stop_key} para iniciar/parar o AutoClicker")
        print("O programa está rodando. Pressione Ctrl+C para sair.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nSaindo do AutoClicker...")
            self.stop_clicking()

if __name__ == "__main__":
    autoclicker = AutoClicker()
    autoclicker.run()