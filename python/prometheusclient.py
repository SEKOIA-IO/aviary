import requests
import time


class PrometheusClient:
    def __init__(self, url):
        self.baseURL = url + "/api/v1"
        self.queryURL = self.baseURL + "/query"

    def getLastValue(self, query):
        r_time = requests.get(self.queryURL, params={"query": "time()"})
        current_time = time.time()
        if r_time.status_code == 200:
            result = r_time.json()["data"]["result"]
            if len(result):
                current_time = result[0]

        r = requests.get(self.queryURL, params={"time": current_time, "query": query})
        if r.status_code == 200:
            result = r.json()["data"]["result"]
            if len(result):
                return result[0]["value"][1]
            else:
                return None
        else:
            return False
