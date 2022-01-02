# Secure-Chat

...is an encrypted chat app, which you can self-host on any machine with Python 3 installed.

### How to install

Run the install.bat file, which is located in the client/ folder to install all required dependencies.

Configure the config.yaml file in the client folder like this

```
server:
    hostlist:
        - "<server_ip>"
    port: 10127
client:
    random-nick: true
    tui: true
```

...and the config.yaml in the server folder like this:

```
server:
    host: "0.0.0.0"
    port: 10127
```

### Demo Pictures

![alt text](https://secure-msg.000webhostapp.com/demo1.jpg "Demo Picture")
