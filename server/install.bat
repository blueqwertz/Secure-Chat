@echo off
py -m pip install names
py -m pip install bson
py -m pip uninstall pycrypto
py -m pip uninstall crypto 
py -m pip install pycryptodome
py -m pip install uuid
py -m pip install pyyaml
py -m pip install hmac