from ucsc import ucsc

from flask import Flask
from flask_compress import Compress

app = Flask(__name__)
Compress(app)
app.register_blueprint(ucsc)
