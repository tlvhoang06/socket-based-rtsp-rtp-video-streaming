import sys, socket
from ServerWorker import ServerWorker

class Server:
    def main(self):
        try:
            SERVER_PORT = int(sys.argv[1])
        except:
            print("[Usage: Server.py Server_port]")
            return
        rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rtspSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rtspSocket.bind(('', SERVER_PORT))
        rtspSocket.listen(5)
        print(f"[INFO] RTSP Server listening on port {SERVER_PORT}")
        while True:
            clientInfo = {}
            clientInfo['rtspSocket'] = rtspSocket.accept()
            ServerWorker(clientInfo).run()

if __name__ == "__main__":
    (Server()).main()
