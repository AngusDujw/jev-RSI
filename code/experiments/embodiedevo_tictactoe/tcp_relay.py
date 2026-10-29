"""Expose only experiment tunnel ports to the isolated Docker bridge."""
import argparse
import select
import socket
import socketserver


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(("127.0.0.1",self.server.target)) as upstream:
            peers={self.request:upstream,upstream:self.request}
            while True:
                readable,_,_=select.select(list(peers),[],[],60)
                if not readable:
                    continue
                for source in readable:
                    data=source.recv(65536)
                    if not data:
                        return
                    peers[source].sendall(data)


if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--bind",required=True); p.add_argument("--port",type=int,required=True)
    a=p.parse_args()
    with socketserver.ThreadingTCPServer((a.bind,a.port),Handler) as server:
        server.target=a.port
        server.serve_forever()
