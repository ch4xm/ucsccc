from ucsc import ucsc, main, fullcrawl

from flask import Flask
from flask_compress import Compress
from flask_cors import CORS
from threading import Thread

# scrape_thread = Thread(target=fullcrawl)
# scrape_thread.start()
print('Starting background thread for scraping menu...')
# thread = Thread(target=main)
# thread.start()
app = Flask(__name__)
CORS(app, resources={r"/api": {"origins": "*"}})
Compress(app)
app.register_blueprint(ucsc)
print('Website is up')