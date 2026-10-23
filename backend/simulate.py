import requests
import json

# We need a JWT token for the user to make a request to /v1/cards
# Since we don't have the user token, this will return 401. 
# We need to simulate the exact same call or just read the flask output
