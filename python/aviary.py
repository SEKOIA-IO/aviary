# std
import os
import threading
import yaml

# sekoia
from prometheusclient import PrometheusClient
from birdwatcher import BirdWatcher
from kubernetesinterface import KubernetesInterface
from admin_server import AdminServer


class Aviary:
    def __init__(self):
        self.canaries = []
        self.threads = []
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "canaries.yaml")) as f:
            self.config = yaml.load(f.read(), Loader=yaml.SafeLoader)

        self.prom = PrometheusClient(self.config["prometheus-base-url"])
        del self.config["prometheus-base-url"]

        self.kube = KubernetesInterface(namespace=self.config.get("namespace", "sic"))
        del self.config["namespace"]

        for canary in self.config.keys():
            self.addCanary(canary, self.config[canary])

        self.cli_server = AdminServer(8888, self.canaries)

    def addCanary(self, deployment, config):
        c = BirdWatcher(deployment, config, self.prom, self.kube)
        if c.initCanary():
            self.canaries += [c]
            self.threads += [threading.Thread(target=c.watch)]
            self.threads[-1].start()
            return c
        return False

    def wait(self):
        for t in self.threads:
            t.join()


a = Aviary()
a.wait()
