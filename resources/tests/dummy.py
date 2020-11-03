from prometheus_client import start_http_server, Counter
import time
import sys

arg = "work"  # can be work, fail, fail-in-metrics
if len(sys.argv) > 1:
    arg = sys.argv[1]

print(arg)


c = Counter("aviary_tester_failures", "Artificial number of failures")

if __name__ == "__main__":
    # Start up the server to expose the metrics.
    start_http_server(8000)
    # Generate some requests.
    while True:
        time.sleep(1)
        if arg == "fail-in-metrics":
            c.inc()
        elif arg == "fail":
            print("Guess i'll die")
            sys.exit(3)
