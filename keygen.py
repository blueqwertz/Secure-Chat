from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
import os

os.chdir(os.path.dirname(os.path.realpath(__file__)))

keyPair = RSA.generate(4096)
private_key = keyPair.export_key("PEM")
public_key = keyPair.publickey().exportKey("PEM")

with open("server/modules/.private.pem", "wb") as f:
    f.write(private_key)
with open("server/modules/public.pem", "wb") as f:
    f.write(public_key)
