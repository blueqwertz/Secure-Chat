import os
import socket
from struct import pack
import threading
from colorama import Fore, Style
import colorama
from tabulate import tabulate
from modules.chat import Chat
import modules.crypto as crypto
import bson
import uuid
import yaml
import names
import requests
import hashlib
import tkinter as tk
from tkinter import filedialog
import sys
import time

HEADER_SIZE = 1024
os.chdir(os.path.dirname(os.path.realpath(__file__)))


class Client(object):

    def __init__(self) -> None:

        self.format = "utf-8"

        self.conf = self.read_conf()

        self.hostlist = None

        self.host = None
        self.port = None

        self.verbose = "-v" in sys.argv

        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.auth = None
        self.nickname = os.getlogin().lower()

        self.id = None
        self.room = "main"

        self.last_invite_room = None
        self.last_request_user = None

        self.server_pub = requests.get("https://secure-msg.000webhostapp.com/public.pem").text.replace("\\n", "\n").encode(self.format)

        self.useRandomNick = None

        self.userlist = {}
        self.chatrooms = []
        self.threads = []

        self.version = "1.0.0"

        self.tui = None
        self.chat = None

        self.file_directory = os.path.join(os.path.expanduser('~/Documents'), "SecureMessage")
        self.check_dir_path()

        self.unmanaged_packages = []

        self.bytes_sent = 0
        self.bytes_received = 0
        self.connection_start = None

    def start(self):
        """
        Start the client
        """
        colorama.init(convert=True)

        self.hostlist = self.conf["server"]["hostlist"]
        self.port = self.conf["server"]["port"]

        self.useRandomNick = self.conf["client"]["random-nick"]
        self.tui = self.conf["client"]["tui"]

        if self.tui:
            self.chat = Chat(debug=True)
        self.print("Starting Secure-Chat Client", color="green")
        if self.verbose:
            self.print("debug: Got server public key")
        crypto.generate_key(self.verbose)
        if self.verbose:
            self.print("\rdebug: Generated key pair   ")
        for addr in self.hostlist:
            try:
                if addr == "localhost":
                    addr = socket.gethostbyname(socket.gethostname())
                if addr.startswith("env"):
                    addr = os.environ[addr[4:]]
                if self.verbose:
                    self.print("debug: Trying to connect to {}:{}".format(addr, self.port))
                self.client.connect((addr, self.port))
                self.host = addr
                break
            except socket.error:
                continue
        if not self.host:
            self.print("[-] Could not connect to Server", color="red")
            time.sleep(3)
            sys.exit()
        if self.verbose:
            self.print("debug: Connected to {}".format(self.host))

        self.print("Connected to Server", color="green")

        self.connection_start = time.time()

        self.auth = input("Verification code: ")

        if self.useRandomNick:
            self.nickname = names.get_first_name().lower()

        self.threads.append(threading.Thread(target=self.thread_receive, daemon=True).start())
        self.threads.append(threading.Thread(target=self.thread_handle_package, daemon=True).start())

        if self.tui:
            self.chat.tb.start()
            self.chat._change_user_name(f"{self.nickname}@{self.room}")
            self.chat._change_user_name("{}@{}".format(self.nickname, self.room))
            self.chat._update_user_list(self.userlist, self.room)
            self.chat.writeCallBack = self.thread_user_input
            self.chat.tb.update()
        else:
            self.threads.append(threading.Thread(target=self.thread_user_input).start())

    ###################
    # BASIC FUNCTIONS #
    ###################

    def recv(self):
        """
        Receive a package from the server
        :return:"""
        header = int.from_bytes(self.client.recv(HEADER_SIZE), "big")
        data = self.client.recv(header)
        while len(data) < header:
            data += self.client.recv(header - len(data))
        self.bytes_received += header + len(str(header))
        package = bson.loads(data)
        return package

    def send(self, packet_type, packet_data):
        """
        Send a package to the server
        :param packet_type:
        :param packet_data:
        :return:"""
        package = bson.dumps({"type": packet_type, "data": packet_data})
        header = len(package).to_bytes(HEADER_SIZE, "big")

        self.bytes_sent += len(package) + (len(str(len(package))))

        self.client.send(header)
        self.client.send(package)
        return True

    def broadcast(self, package_type="message", package_data=None):
        """
        Broadcast a package to all users in the current room
        :param package_type:
        :param package_data:
        :return:"""
        myUserList = [user for user in self.userlist if self.userlist[user]["room"] == self.room]
        if len(myUserList) == 0:
            return
        if package_type == "message":
            crypto.generate_aes_key()
            package_data["messagedata"], package_data["nonce"] = crypto.aes_encrypt(package_data["messagedata"])
        if package_type == "file":
            crypto.generate_aes_key()
            self.print("Encrypting file...         ", end="\r")
            package_data["filedata"], package_data["nonce"] = crypto.aes_encrypt(package_data["filedata"])
            package_data["fingerprint"], package_data["fingerprintnonce"] = crypto.aes_encrypt(package_data["fingerprint"])
            self.print("Sending file...          ", end="\r")
        for user in myUserList:
            user = self.userlist[user]
            package_data_copy = package_data.copy()
            if package_type == "message":
                package_data_copy["key"] = crypto.encrypt(crypto.AES_KEY, user["key"])
            if package_type == "file":
                package_data_copy["name"] = crypto.encrypt(package_data_copy["name"], user["key"])
                package_data_copy["key"] = crypto.encrypt(crypto.AES_KEY, user["key"])
                # self.print("Sendig file to {}...         ".format(user["nick"]), end="\r")
            self.send(package_type, {"message": package_data_copy, "id": user["id"]})

    def print(self, text, color="white", end="\n"):
        """
        Prints text to the terminal.
        :param text: Text to print
        :param color: Color of the text
        :return: None"""
        if self.tui and self.chat.tb.started:
            self.chat.print(text, color, end)
        else:
            if color == "dim":
                print("{}{}{}".format(Style.DIM, text, Style.RESET_ALL), end=end)
            elif color == "green":
                print("{}{}{}".format(Fore.GREEN, text, Style.RESET_ALL), end=end)
            elif color == "red":
                print("{}{}{}".format(Fore.RED, text, Style.RESET_ALL), end=end)
            elif color == "yellow":
                print("{}{}{}".format(Fore.YELLOW, text, Style.RESET_ALL), end=end)
            elif color == "cyan":
                print("{}{}{}".format(Fore.CYAN, text, Style.RESET_ALL), end=end)
            elif color == "magenta":
                print("{}{}{}".format(Fore.MAGENTA, text, Style.RESET_ALL), end=end)
            elif color == "light-magenta":
                print("{}{}{}".format(Fore.LIGHTMAGENTA_EX, text, Style.RESET_ALL), end=end)
            else:
                print(text, end=end)

    ###########
    # THREADS #
    ###########

    def thread_handle_package(self):
        """
        Thread that handles packages from the server
        :return:"""
        while True:
            if len(self.unmanaged_packages) > 0:
                message = self.unmanaged_packages.pop(0)

                if message["type"] == "message":
                    data = message["data"]
                    data["key"] = crypto.decrypt(data["key"], decodeData=False)
                    dec_message = crypto.aes_decrypt(data["messagedata"], data["key"], data["nonce"], True)
                    self.print(str(dec_message), color=["white"])
                    continue

                elif message["type"] == "whisper":
                    key = crypto.decrypt(message["data"]["key"], decodeData=False)
                    message = crypto.aes_decrypt(message["data"]["message"], key, message["data"]["nonce"], True)
                    self.print(str(message), color="magenta")

                elif message["type"] == "file":
                    data = message["data"]
                    data["key"] = crypto.decrypt(data["key"], decodeData=False)
                    data["name"] = crypto.decrypt(data['name'])
                    data["fingerprint"] = crypto.aes_decrypt(data["fingerprint"], data["key"], data["fingerprintnonce"], True)
                    file = open(f'{self.file_directory}/{data["name"]}{data["ext"]}', 'wb')
                    decr = crypto.aes_decrypt(data["filedata"], data["key"], data["nonce"], False)
                    fingerprint = hashlib.sha256(decr).hexdigest()
                    size = len(decr)
                    power = 2**10
                    n = 0
                    labels = {0: 'b', 1: 'kb', 2: 'mb', 3: 'gb', 4: 'tb'}
                    while size > power:
                        size /= power
                        n += 1
                    size = size // 1
                    label = labels[n]
                    self.print(f"File: {data['name']}{data['ext']} ({size} {label})", color="magenta")
                    if fingerprint == data["fingerprint"]:
                        self.print("Signature matches", color="green")
                    else:
                        self.print("Hash does not match", color="red")
                    file.write(decr)
                    file.close()
                    self.send("file-received", {"id": data["id"]})

                elif message["type"] == "nick-change":
                    nickname = message["data"]
                    if self.tui:
                        self.chat._change_user_name(f"{nickname}@{self.room}")

                elif message["type"] == "error":
                    self.print(message["data"], color="red")
                    self.client.close()

                elif message["type"] == "accepted":
                    if self.verbose:
                        self.print("debug: accepted by server")
                    self.print("Type /help for a list of commands", color="cyan")
                    self.print(f"you joined!", color="cyan")
                    continue

                elif message["type"] == "server-auth":
                    if self.verbose:
                        self.print("debug: client-server authentication")
                    if self.server_pub and self.server_pub != message["data"]:
                        self.print("Server public key does not match!", color="red")
                        self.print("The connection might be interrupted by a third party", color="red")
                    self.send("key", crypto.public_key)
                    continue

                elif message["type"] == "info":
                    if self.verbose:
                        self.print("debug: authenticating to {}:{} as '{}'".format(self.host, self.port, self.nickname))
                        self.print("debug: client info exchange")
                    self.send(
                        "info",
                        {"nickname": crypto.encrypt(self.nickname, self.server_pub),
                         "version": self.version,
                         "2fa": crypto.encrypt(self.auth, self.server_pub)})
                    if self.verbose:
                        self.print("debug: sent 2fa authentication")
                    continue

                elif message["type"] == "key":
                    key = message["data"]["pub_key"]
                    id = message["data"]["id"]
                    user_nickname = message["data"]["nickname"]
                    room = message["data"]["room"]
                    self.userlist[id] = {
                        "key": key,
                        "nick": user_nickname,
                        "room": room,
                        "id": id}
                    if self.tui:
                        self.chat._update_user_list(self.userlist, self.room)
                    continue

                elif message["type"] == "remove-user":
                    user_id = message["data"]["id"]
                    try:
                        self.print("{} left".format(
                            self.userlist[user_id]["nick"]), color="cyan")
                        del self.userlist[user_id]
                    except KeyError:
                        pass
                    if self.tui:
                        self.chat._update_user_list(self.userlist, self.room)
                    continue

                elif message["type"] == "remove-all":
                    self.userlist = {}
                    continue

                elif message["type"] == "new-room":
                    if not message["data"] in self.chatrooms:
                        self.chatrooms.append(message["data"])
                    continue

                elif message["type"] == "del-room":
                    if message["data"] in self.chatrooms:
                        self.chatrooms.remove(message["data"])

                elif message["type"] == "room-change":
                    self.room = message["data"]
                    self.print("Joined room {}".format(message["data"]), color="green")
                    if self.tui:
                        self.chat._change_user_name(
                            "{}@{}".format(self.nickname, message["data"]))
                        self.chat._update_user_list(self.userlist, self.room)
                    continue

                elif message["type"] == "notification":
                    self.print(message["data"], color="cyan")
                    continue

                elif message["type"] == "warning":
                    self.print(message["data"], color="yellow")
                    continue

                elif message["type"] == "user-info-change":
                    # self.print(pub_keys[message["data"]["id"]])
                    if message["data"]["id"] in self.userlist:
                        self.userlist[message["data"]["id"]] = message["data"]["user"]
                        if self.tui:
                            self.chat._update_user_list(self.userlist, self.room)

                elif message["type"] == "nick-warning":
                    self.print("Nickname already taken", color="yellow")
                    self.print(
                        "Your new nickname: {}".format(
                            message["data"]
                        ), color="cyan"
                    )
                    self.print("You can change it using /nick", color="cyan")
                    self.nickname = message["data"]
                    if self.tui:
                        self.chat._change_user_name("{}@{}".format(self.nickname, self.room))

                elif message["type"] == "invite-req":
                    self.print(
                        "Got invited to room: {}".format(message["data"]),
                        color="green",
                    )
                    self.last_invite_room = message["data"]

                elif message["type"] == "file-received":
                    self.print("{} received the file".format(message["data"]), color="green")

                elif message["type"] == "join-req":
                    self.last_request_user = message["data"]
                    self.print("{} wants to join the room".format(message["data"]), color="cyan")

                elif message["type"] == "kick":
                    self.print("You were kicked from the room", color="red")

                elif message["type"] == "clearall":
                    os.system('cls' if os.name == 'nt' else 'clear')
                    if self.tui:
                        self.chat.tb.clear_text_items("setup", "Chat")
                        self.chat.tb.update()
                    self.print("Server cleared all messages", color="yellow")
                    continue

                else:
                    self.print("Could not resolve message")
                    continue

    def thread_receive(self):
        """
        Thread to receive messages from the server
        """
        while True:
            try:
                package = self.recv()
                self.unmanaged_packages.append(package)
            except socket.error:
                self.print("[-] Disconnected from Server", color="red")
                if self.verbose:
                    self.print("debug: byted per second sent/received: {}/{}".format(self.bytes_sent / (time.time() - self.connection_start) / 1000, self.bytes_received / (time.time() - self.connection_start) / 1000))
                    self.print("debug: exit status 0")
                return

    def thread_user_input(self, user_input=None):
        while True:
            if not self.tui:
                user_input = input("")
            if user_input.startswith("/"):
                cmd = user_input.replace("/", "")
                cmd = cmd.split(" ")
                cmd[0] = cmd[0].lower()
                cmd = " ".join(cmd)
                self.handle_command(cmd.strip())
            elif len(user_input) > 0:
                if self.tui:
                    self.print(f"[{self.nickname}] {user_input}", color=["white"])
                self.broadcast("message", {"messagedata": "{}: {}".format(self.nickname, user_input)})
            if self.tui:
                return

    ###################
    # EXTRA FUNCTIONS #
    ###################

    def read_conf(self):
        with open('config.yaml', 'r') as file:
            try:
                conf = yaml.safe_load(file)
                return conf
            except yaml.YAMLError as exc:
                print(exc)

    def save_conf(self):
        with open(r"config.yaml", 'w') as file:
            try:
                yaml.dump(self.conf, file)
            except yaml.YAMLError as exc:
                print(exc)

    def check_dir_path(self):
        """
        Check if the directory path is valid
        """
        if not os.path.exists(self.file_directory):
            self.print("Created directory for files at {}".format(self.file_directory.replace("/", "\\")), color="cyan")
            os.mkdir(self.file_directory)

    def handle_command(self, cmd):
        """
        Handle commands
        """
        if cmd == "exit":
            self.client.close()

        elif cmd == "leave":
            self.send("leave", None)

        elif cmd == "clear":
            if self.tui:
                self.chat.tb.clear_text_items("setup", "Chat")
            else:
                os.system("cls" if os.name == "nt" else "clear")

        elif cmd == "help":
            commands = [
                ["/clear", "clear terminal"],
                ["/whisper <nickname>", "whisper to a user"],
                ["/chatroom <name>", "create room"],
                ["/invite <nickname>", "invite user to room *"],
                ["/join (<chatroom>)", "join chatroom"],
                ["/kick <username>", "kick user from room *"],
                ["/accept (<nickname>)", "accept join request *"],
                ["/decline (<nickname>)", "decline join request *"],
                ["/leave", "leave room"],
                ["/nick <nickname>", "change nickname"],
                ["/file (<filepath>)", "send file"],
                ["/list", "list users"],
                ["/exit", "exit chat"],
            ]
            table = tabulate(commands, tablefmt="plain")
            for line in table.split("\n"):
                self.print(line, color="magenta")
            self.print("* Requires admin priviliges", color="magenta")

        elif cmd == "list":
            room_list = {self.room: ["you"]}
            for user in self.userlist.values():
                if user["room"] in room_list:
                    room_list[user["room"]].append(user["nick"])
                else:
                    room_list[user["room"]] = [user["nick"]]
            for key, value in room_list.items():
                if key == self.room and not self.tui:
                    self.print(f"{key}: {', '.join(value)}", color="light-magenta")
                else:
                    self.print(f"{key}: {', '.join(value)}", color="magenta")

        elif cmd.startswith("whisper"):
            try:
                name = cmd.split(" ")[1].lower()
            except BaseException:
                self.print("[-] Invalid input", color="yellow")
                return
            whisper_id = None
            whisper_room = None
            for id in self.userlist:
                if self.userlist[id]["nick"] == name:
                    whisper_id = id
                    whisper_room = self.userlist[id]["room"]
                    break
            if whisper_id:
                msg = cmd
                msg = msg.replace(name, "").replace("whisper", "").strip()
                self.print("you whispered to {}: {}".format(
                    name, msg), color="magenta")
                message = "{} whispered to you: {}".format(self.nickname, msg)
                crypto.generate_aes_key()
                encrypted_message, nonce = crypto.aes_encrypt(message)
                key = crypto.encrypt(crypto.AES_KEY, self.userlist[whisper_id]["key"])
                self.send(
                    "whisper",
                    {
                        "message": encrypted_message,
                        "key": key,
                        "nonce": nonce,
                        "id": whisper_id,
                        "room": whisper_room
                    },
                )
            else:
                self.print("[-] Could not find user", color="yellow")

        elif cmd.startswith("chatroom"):
            if not len(cmd.split(" ")) == 2:
                self.print("[-] Invalid chatroom name", color="yellow")
                return
            name = cmd.split(" ")[1]
            self.send("create-chatroom", name)

        elif cmd.startswith("nick"):
            if not len(cmd.split(" ")) == 2:
                self.print("[-] Invalid chatroom name", color="yellow")
                return
            name = cmd.split(" ")[1]
            for user in self.userlist:
                if self.userlist[user]["nick"] == name:
                    self.print("Nickname already taken", color="yellow")
                    return
            nickname = name
            self.send("nick-change", crypto.encrypt(name, self.server_pub))

        elif cmd.startswith("invite"):
            try:
                name = cmd.split(" ")[1]
            except BaseException:
                self.print("[-] Invalid input")
                return
            whisper_id = None
            whisper_room = None
            for id in self.userlist:
                if self.userlist[id]["nick"] == name:
                    whisper_id = id
                    whisper_room = self.userlist[id]["room"]
                    break
            if whisper_id:
                self.send(
                    "invite",
                    {
                        "room": self.room,
                        "id": whisper_id,
                        "invite_room": whisper_room},
                )
            else:
                self.print("[-] Could not find user", color="yellow")

        elif cmd.startswith("join"):
            name = None
            if len(cmd.split(" ")) == 2:
                name = cmd.split(" ")[1]
            if self.last_invite_room:
                name = self.last_invite_room
            if not name:
                self.print("[-] Invalid input", color="yellow")
            self.send(
                "join",
                name,
            )

        elif cmd.startswith("file"):
            def send_file(filepath):
                """check if file exists and broadcast it"""
                if os.path.isfile(filepath):
                    data = open(path, 'rb')
                    l = data.read()
                    fingerprint = hashlib.sha256(l).hexdigest()
                    size = os.path.getsize(path)
                    if size > 100000000:  # 100MB
                        self.print("[-] Filesize to big (max 100MB)", color="yellow")
                        return
                    ext = os.path.splitext(path)[1]
                    # name = path.replace("\\", "/").split("/")[-1].replace(ext, "")
                    name = str(uuid.uuid4().hex)[0:8]
                    self.broadcast("file", {
                        "filedata": l, "name": name, "ext": ext, "fingerprint": fingerprint})
                else:
                    self.print("[-] File does not exist", color="yellow")
            if cmd == "file":
                path = self.file_select()
                if path is None:
                    return
                send_file(path)

            elif len(cmd.split(" ")) > 1:
                path = cmd.replace("file", "").replace('"', '').strip()
                if path is None:
                    return
                send_file(path)

            else:
                self.print("[-] Invalid input", color="yellow")

        elif cmd.startswith("kick"):
            try:
                name = cmd.split(" ")[1]
            except BaseException:
                self.print("[-] Invalid input", color="yellow")
                return
            kick_id = None
            kick_room = None
            for id in self.userlist:
                if self.userlist[id]["nick"] == name:
                    kick_id = id
                    kick_room = self.userlist[id]["room"]
                    break
            if kick_id:
                self.send(
                    "kick",
                    kick_id,
                )
            else:
                self.print("[-] Could not find user", color="yellow")

        elif cmd.startswith("accept"):
            if len(cmd.split(" ")) == 1:
                if self.last_request_user:
                    cmd = f"accept {self.last_request_user}"
                    self.last_request_user = None
            try:
                name = cmd.split(" ")[1]
            except BaseException:
                self.print("[-] Invalid input", color="yellow")
                return
            requested_id = None
            requested_room = None
            for id in self.userlist:
                if self.userlist[id]["nick"] == name:
                    requested_id = id
                    requested_room = self.userlist[id]["room"]
                    break
            if requested_id:
                self.send(
                    "accept",
                    {"id": requested_id, "room": requested_room},
                )
            else:
                self.print("[-] Could not find user", color="yellow")

        elif cmd.startswith("decline"):
            if len(cmd.split(" ")) == 1:
                if self.last_request_user:
                    cmd = f"accept {self.last_request_user}"
                    self.last_request_user = None
            try:
                name = cmd.split(" ")[1]
            except BaseException:
                self.print("[-] Invalid input", color="yellow")
                return
            requested_id = None
            requested_room = None
            for id in self.userlist:
                if self.userlist[id]["nick"] == name:
                    requested_id = id
                    requested_room = self.userlist[id]["room"]
                    break
            if requested_id:
                self.send(
                    "decline",
                    {"id": requested_id, "room": requested_room},
                )
            else:
                self.print("[-] Could not find user", color="yellow")

        else:
            self.print(
                "[-] Could not find command. Type /help for list of commands",
                color="yellow")

    def file_select(self):
        """
        Opens a file selection dialog"""
        try:
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilename()
            root.destroy()
            return file_path
        except Exception:
            return None


client = Client()
client.start()
