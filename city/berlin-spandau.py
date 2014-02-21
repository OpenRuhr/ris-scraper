# encoding: utf-8

RS = "110050005005"  # Berlin Spandau

# Stadtname für Logfile
CITY = 'berlin-spandau'

# Currently, only "mongodb" is supported
DB_TYPE = 'mongodb'

# Name of the MongoDB database
DB_NAME = 'scrapearis'

# Use "localhost" if MongoDB is running on the same machine
DB_HOST = 'localhost'

# MongoDB default port is 27017
DB_PORT = 27017

# SessionNet base url, should include trailing slash
BASE_URL = 'http://www.berlin.de/ba-spandau/bvv-online/'

# Name to identify your crawler to the server
USER_AGENT_NAME = 'scrape-a-ris/0.1'

# Number of seconds to wait between requests. Increase this
# if the systems behaves unstable (seconds)
WAIT_TIME = 0.2

# Log level (DEBUG, INFO, WARNING, ERROR or CRITICAL)
LOG_LEVEL = 'INFO'
# File to log to
LOG_BASE_DIR = '/var/log/ris-scraper/'

#Scraper Type
SCRAPER_TYPE = 'ALLRIS'

###### Result normalization mapping

RESULT_STRINGS = {
}


FILE_EXTENSIONS = {
    'application/pdf': 'pdf',
    'image/tiff': 'tif',
    'image/jpeg': 'jpg',
    'application/vnd.ms-powerpoint': 'pptx',
    'application/msword': 'doc',
    'application/zip': 'zip',
    'text/plain': 'txt'
}

