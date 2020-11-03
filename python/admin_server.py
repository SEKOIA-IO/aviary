import socket
import threading

HELP_STRING = """
Commands :

- ls : list services. '*' = bypassed, '~' = currently deploying
- bypass X : next deployment of X will be direct
- nobypass X : next deployment of X will be normal
- abort X : abort running deployment
"""


class AdminServer:
    def __init__(self, port, canaries):
        self.port = port
        self.canaries = canaries
        self.server_thread = threading.Thread(target=self.server)
        self.server_thread.start()
        self.server_thread.join()
        print("AdminServer crashed")

    def server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", self.port))
            s.listen(1)

            while True:
                self.conn, self.addr = s.accept()
                with self.conn:
                    print("[AdminServer] Connection from", self.addr)
                    self.reply(HELP_STRING, prompt=False)
                    self.reply("List of services : ", prompt=False)
                    self.send_list()
                    while True:
                        data = self.conn.recv(1024)
                        if not data:
                            print("[AdminServer] Disconnect :", self.addr)
                            break
                        self.handle(data)

    def reply(self, data="", prompt=True):
        msg = data + "\n"
        if prompt:
            msg += "_> "
        self.conn.sendall(msg.encode("utf-8"))

    def send_list(self):
        ls = ""
        for i in range(len(self.canaries)):
            c = self.canaries[i]
            notes = ""
            if c.bypass_next_deployment:
                notes += "*"
            if c.deploying:
                notes += "~"
            ls += f"[{i}] {notes}{c.baseDeploymentName}\n"
        self.reply(ls)

    def handle(self, data):
        data = data.strip().decode()
        chunks = data.split()
        if not len(chunks):
            self.reply()
            return
        if len(chunks) == 2:
            try:
                canary_i = int(chunks[-1])
                canary = self.canaries[canary_i]
                canary_name = canary.baseDeploymentName
            except Exception:
                self.reply("Invalid command.")
                return

        if data == "ls":
            return self.send_list()
        if chunks[0] == "bypass":
            canary.bypass_next_deployment = True
            return self.reply(
                f"Next deployment of {canary_name} will be done directly.\nCancel with 'nobypass {canary_i}'"
            )
        if chunks[0] == "nobypass":
            canary.bypass_next_deployment = False
            return self.send_list()
        if chunks[0] == "abort":
            canary.abort = True
            return self.reply(f"Aborting deployment of {canary_name} ...")
        self.reply("Invalid command")
