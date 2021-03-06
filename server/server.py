import names
import bson
import threading
import socket
import modules.crypto as crypto
import time
import sys
import uuid
import os
import yaml
import pyotp
# import qrcode_terminal

HEADER_SIZE = 1024
BUFFERSIZE = 2 ** 16
os.chdir(os.path.dirname(os.path.realpath(__file__)))


class Client():

    def __init__(self, socket, addr) -> None:

        self.socket = socket
        self.addr = addr
        self.id = None
        self.nickname = None
        self.public_key = None
        self.room = None

    def send(self, package_type, package_data):
        """Send a package to the client."""
        package = bson.dumps({"type": package_type, "data": package_data})
        header = len(package).to_bytes(HEADER_SIZE, "big")

        try:
            self.socket.send(header)
            self.socket.send(package)
        except socket.error:
            raise socket.error

        return True

    def recv(self):
        """Receive a package from the client."""
        try:
            header = int.from_bytes(self.socket.recv(HEADER_SIZE), "big")
            data = self.socket.recv(header)
            while len(data) < header:
                data += self.socket.recv(header - len(data))
            package = bson.loads(data)
        except socket.error:
            raise socket.error

        return package


class Server():

    def __init__(self) -> None:

        self.debug = True
        self.conf = self.read_conf()

        self.host = self.conf["server"]["host"]
        self.port = self.conf["server"]["port"]

        self.format = "utf-8"

        self.version = "1.0.0"

        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.bind((self.host, self.port))
            self.server.listen()
        except Exception:
            print("Coult not bind server to {} -p {}".format(self.host, self.port))
            sys.exit()

        self.connections = {"main": {"admin": None, "clients": {}, "invited-ids": [], "requests": []}}
        self.connection_history = {}
        self.connection_ban_time = 120

        self.authkey = os.environ["authkey"].encode(self.format)
        self.totpgenerator = pyotp.TOTP(self.authkey)
        # qrcode_terminal.draw("otpauth://totp/Secure-Chat?secret=5CJB43ZL3TWYGXS6")

        self.threads = [
            threading.Thread(target=self.listen, daemon=True),
            threading.Thread(target=self.console),
            threading.Thread(target=self.checks, daemon=True),
        ]

        self.public_key = None

    def start(self):
        """
        Start the server."""
        crypto.generate_key()
        self.public_key = crypto.public_key

        for thread in self.threads:
            thread.start()

    ###################
    # BASIC FUNCTIONS #
    ###################

    def listen(self):
        """Listen for incoming connections."""
        self.log(f"Listening on {self.host} port {self.port}")
        failed = 0
        while True:
            try:
                client, address = self.server.accept()
                address = address[0]
                self.log("Incomming connection")
                client = Client(socket=client, addr=address)
                if not self.fail2ban(address):
                    client.send("error", "[-] Connection refused")
                    continue
                failed = 0
                threading.Thread(
                    target=self.login,
                    args=(client, )
                ).start()
            except:
                print("[-] Error while waiting for users\r")
                failed += 1
                if failed > 10:
                    return
                continue

    def login(self, client):
        """Login a client."""
        try:
            # SERVER KEY EXCHANGE
            client.send("server-auth", crypto.public_key)
            pub_key = client.recv()["data"]

            # CLIENT INFO RECV
            client.send("info", None)
            client_info = client.recv()["data"]

            # CLIENT INFO DECRYPTION
            client_info["nickname"] = crypto.decrypt(client_info["nickname"]).strip()
            client_info["2fa"] = crypto.decrypt(client_info["2fa"])

            if len(client_info["nickname"]) == 0:
                client.send("error", "[-] Please enter nickname")

            if client_info["version"] != self.version:
                client.send("error", "[-] Please update your client")
                return

            if client_info["nickname"] != client_info["nickname"].lower():
                client_info["nickname"] = client_info["nickname"].lower()
                client.send("nick-change", client_info["nickname"])

            def nick_dup(nick):
                for room in self.connections:
                    for client_id in self.connections[room]["clients"]:
                        if self.connections[room]["clients"][client_id].nickname == nick:
                            return True
                return False

            # CHECK NICKNAME DUPLICATE
            nick_change = False
            while nick_dup(client_info["nickname"]):
                nick_change = True
                client_info["nickname"] = names.get_first_name().lower()

            if nick_change:
                client.send("nick-warning", client_info["nickname"])

            # 2FA
            if not self.debug:
                if not str(client_info["2fa"]) == str(self.totp()):
                    client.send("error", "[-] Invalid 2FA key")
                    return

            id = str(uuid.uuid4())

            # CLIENT OBJECT
            client.nickname = client_info["nickname"]
            client.public_key = pub_key
            client.id = id
            client.room = "main"

            # PUBLIC-KEY EXCHANGE
            self.key_exchange(client)

            # CHATROOM LIST EXCHANGE
            for room in self.connections:
                client.send("new-room", room)

            # JOIN MESSAGE
            self.broadcast(
                "notification",
                "{} joined!".format(client_info["nickname"]),
                client,
                "main",
            )
            self.connections["main"]["clients"][id] = client

            # REM CONNECTION HISTORY
            try:
                del self.connection_history[client.addr]
            except KeyError:
                pass

            # USER RECV/SEND THREAD
            try:
                client.send("accepted", None)
                self.log("Client accepted")
                threading.Thread(target=self.handle, args=(client,)).start()
            except Exception:
                pass

        except socket.error:
            pass

    def broadcast(self, package_type, package_data, client, room):
        """Broadcast a package to all clients in a room."""
        if room is None:
            for room in self.connections:
                for user in self.get_clients(room):
                    user.send(package_type, package_data)
            return
        for id, user in self.connections[room]["clients"].items():
            if client is not None:
                if id == client.id and not id is None:
                    continue
            try:
                user.send(package_type, package_data)
            except Exception:
                pass

    def handle(self, client):
        """Handle a client."""
        while True:
            try:
                message = client.recv()
                if message is None:
                    raise socket.error
                if message["type"] == "message":
                    try:
                        room = client.room
                        if room in message["data"]:
                            room = message["data"]["room"]
                        self.connections[room]["clients"][message["data"]["id"]].send("message", message["data"]["message"])
                    except KeyError:
                        pass
                elif message["type"] == "whisper":
                    try:
                        self.connections[message["data"]["room"]]["clients"][message["data"]["id"]].send("whisper", message["data"])
                    except KeyError:
                        pass
                elif message["type"] == "create-chatroom":
                    self.remove_empty()
                    if message["data"] in self.connections:
                        client.send("warning",
                                    "[-] Chatroom name already in use")
                        continue
                    self.connections[message["data"]] = {
                        "admin": client.id,
                        "clients": {client.id: client},
                        "invited-ids": [],
                        "requests": [],
                    }
                    self.join_room(client, message["data"])
                    self.broadcast("new-room", message["data"], client, None)
                elif message["type"] == "nick-change":
                    message["data"] = crypto.decrypt(message["data"])
                    if len(message["data"].strip()) == 0:
                        continue
                    is_in_use = False
                    for room in self.connections.values():
                        for client_id in room["clients"].values():
                            if (client_id.nickname == message["data"]):
                                client.send("warning", "Nickname already taken")
                                is_in_use = True
                                break
                    if not is_in_use:
                        self.broadcast(
                            "notification",
                            "{} is now known as {}".format(client.nickname, message["data"]),
                            None,
                            None,
                        )
                        self.broadcast(
                            "user-info-change",
                            {
                                "id": client.id,
                                "user": {
                                    "id": client.id,
                                    "key": client.public_key,
                                    "nick": message["data"],
                                    "room": client.room,
                                },
                            },
                            client,
                            None,
                        )
                        client.nickname = message["data"]
                        client.send("nick-change", client.nickname)
                elif message["type"] == "invite":
                    if not self.connections[client.room]["admin"] == client.id:
                        continue
                    self.connections[message["data"]["room"]]["invited-ids"].append(
                        message["data"]["id"]
                    )
                    self.connections[message["data"]["invite_room"]]["clients"][message["data"]["id"]].send(
                        "invite-req",
                        message["data"]["room"]
                    )
                elif message["type"] == "join":
                    if not message["data"] in self.connections:
                        client.send("warning", "room does not exist")
                        continue
                    if client.id in self.connections[message["data"]]["invited-ids"]:
                        self.connections[message["data"]]["invited-ids"].remove(client.id)
                        self.join_room(client, message["data"])
                        self.broadcast(
                            "notification",
                            "{} joined the room".format(client.nickname), client, message["data"])
                    else:
                        client.send(
                            "notification",
                            "A join request has been sent to the admin of this room",
                        )
                        self.connections[message["data"]]["clients"][self.connections[message["data"]]["admin"]].send(
                            "join-req",
                            client.nickname
                        )
                        self.connections[message["data"]]["requests"].append(client.id)
                elif message["type"] == "leave":
                    if client.room == "main":
                        continue
                    self.broadcast(
                        "notification",
                        "{} left the room".format(client.nickname),
                        client,
                        client.room,
                    )
                    client.send("notification", "You left the room")
                    if self.connections[client.room]["admin"] == client.id:
                        room_ids = []
                        for id, user in self.connections[client.room]["clients"].items():
                            if id != client.id:
                                room_ids.append(id)
                        if len(room_ids) > 0:
                            self.connections[client.room]["admin"] = room_ids[0]
                            self.connections[client.room]["clients"][self.connections[client.room]["admin"]].send("notification", "You are now the admin of this room")
                    self.join_room(client, "main")
                    self.remove_empty()
                elif message["type"] == "file":
                    if message["data"]["id"] in self.connections[client.room]["clients"]:
                        message["data"]["message"]["id"] = client.id
                        self.connections[client.room]["clients"][message["data"]["id"]].send("file", message["data"]["message"])
                elif message["type"] == "file-received":
                    self.connections[client.room]["clients"][message["data"]["id"]].send("file-received", client.nickname)
                elif message["type"] == "kick":
                    if self.connections[client.room]["admin"] != client.id:
                        client.send("warning", "You are not allowed to kick users")
                        continue
                    self.connections[client.room]["clients"][message["data"]].send("kick", None)
                    self.broadcast("notification", "{} was kicked".format(self.connections[client.room]["clients"][message["data"]].nickname), self.connections[client.room]["clients"][message["data"]], client.room)
                    self.join_room(self.connections[client.room]["clients"][message["data"]], "main")
                elif message["type"] == "accept":
                    if client.id == self.connections[client.room]["admin"]:
                        if message["data"]["id"] in self.connections[client.room]["requests"]:
                            self.join_room(self.connections[message["data"]["room"]]["clients"][message["data"]["id"]], client.room)
                            self.broadcast("notification", "{} joined the room".format(self.connections[client.room]["clients"][message["data"]["id"]].nickname), self.connections[client.room]["clients"][message["data"]["id"]], client.room)
                            self.connections[client.room]["requests"].remove(message["data"]["id"])
                elif message["type"] == "decline":
                    if client.id == self.connections[client.room]["admin"]:
                        if message["data"]["id"] in self.connections[client.room]["requests"]:
                            declined_client = self.connections[message["data"]["room"]]["clients"][message["data"]["id"]]
                            if declined_client:
                                declined_client.send("warning", "Your request to join the room has been declined")
                            self.connections[client.room]["requests"].remove(message["data"]["id"])
                else:
                    client.send("warning", "Invalid message type")
            except socket.error:
                try:
                    del self.connections[client.room]["clients"][client.id]
                except KeyError:
                    pass
                self.broadcast(
                    "remove-user",
                    {
                        "id": client.id,
                        "room": client.room
                    },
                    client,
                    None,
                )
                self.remove_empty()
                self.log("{} disconnected".format(client.id))
                return

    ###################
    # EXTRA FUNCTIONS #
    ###################

    def console(self):
        """take admin input from console"""
        try:
            while True:
                message = input("").lower()
                if message == "exit":
                    for room in self.connections:
                        for client in self.connections[room]["clients"]:
                            self.connections[room]["clients"][client].close()
                    return
                if message.startswith("pardon"):
                    try:
                        ip = message.split(" ")[1]
                        if ip in self.connection_history:
                            del self.connection_history[ip]
                    except Exception:
                        print("invalid input")
                if message.startswith("debug"):
                    try:
                        if message.split(" ")[1] == "on":
                            self.debug = True
                        elif message.split(" ")[1] == "off":
                            self.debug = False
                        print("debug mode set to {}".format(self.debug))
                    except Exception:
                        print("invalid input")
                if message.startswith("clearall"):
                    # send clearall message to all clients
                    for room in self.connections:
                        for client in self.connections[room]["clients"]:
                            self.connections[room]["clients"][client].send("clearall", None)
                    print("all messages cleared")
        except Exception:
            pass

    def log(self, message):
        print("[{}] {}".format(time.strftime("%H:%M:%S"), message))

    def fail2ban(self, addr):
        """Ban an address from connecting."""
        if not addr in self.connection_history:
            self.connection_history[addr] = [time.time() / 1000]
            return True
        else:
            self.connection_history[addr].append(time.time() / 1000)
        last60seconds = 0
        for timestamp in self.connection_history[addr]:
            if time.time() / 1000 - timestamp < self.connection_ban_time:
                last60seconds += 1
            else:
                self.connection_history[addr].remove(timestamp)
        if last60seconds > 5:
            return False
        return True

    def key_exchange(self, client):
        """Perform a key exchange with a client."""
        for key, room in self.connections.items():
            for id, user in room["clients"].items():
                if id == client.id:
                    continue
                try:
                    user.send("key", {"pub_key": client.public_key, "id": client.id, "nickname": client.nickname, "room": client.room})
                    client.send("key", {"pub_key": user.public_key, "id": user.id, "nickname": user.nickname, "room": user.room})
                except Exception:
                    pass

    def join_room(self, client, room):
        """Join a room."""
        del self.connections[client.room]["clients"][client.id]
        client.room = room
        self.connections[room]["clients"][client.id] = client
        self.broadcast("user-info-change", {"id": client.id, "user": {"id": client.id, "key": client.public_key, "nick": client.nickname, "room": client.room}}, client, None)
        time.sleep(0.2)
        client.send("room-change", room)

    def totp(self):
        """Generate a TOTP code."""
        return self.totpgenerator.now()

    def get_clients(self, room):
        """Get all clients in a room."""
        clients = []
        for client in self.connections[room]["clients"].values():
            clients.append(client)
        return clients

    def remove_empty(self):
        """Remove empty rooms."""
        empty = []
        for room in self.connections:
            if room == "main":
                continue
            if len(self.connections[room]["clients"]) == 0:
                empty.append(room)
                self.broadcast("del-room", room, None, None)
        for room in empty:
            del self.connections[room]

    def checks(self):
        """Check if a thread is still alive."""
        while True:
            self.remove_empty()
            for thread in self.threads:
                if not thread.is_alive():
                    thread.start()
            time.sleep(60)

    def searchId(self, id):
        """Search for a client by id."""
        for room in self.connections:
            for client in self.connections[room]["clients"].values():
                if client.id == id:
                    return client
        return None

    def read_conf(self):
        with open('config.yaml', 'r') as file:
            try:
                conf = yaml.safe_load(file)
                return conf
            except yaml.YAMLError as exc:
                print(exc)


if __name__ == "__main__":
    server = Server()
    server.start()
