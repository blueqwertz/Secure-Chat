# Secure-Chat

...is an encrypted chat app, which you can self-host on any machine with Python 3 installed.

### How to install

Run the install.bat file, which is located in the client/ folder to install all required dependencies.

Add a config.yaml file with the following structure

```
server:
    hostlist:
        - "<public_ip>"
    port: 10127
client:
    random-nick: true
    tui: true
```
