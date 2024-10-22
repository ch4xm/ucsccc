from ucsc import ucsc, main

from flask import Flask
from flask_compress import Compress
from flask_cors import CORS
from threading import Thread

thread = Thread(target=main)
thread.start()
app = Flask(__name__)
CORS(app, resources={r"/api": {"origins": "*"}})
Compress(app)
app.register_blueprint(ucsc)
