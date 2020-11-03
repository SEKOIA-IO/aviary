# deps
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

# std
import time


class KubernetesInterface:
    def __init__(self, namespace="default"):
        # try to use in-cluster config, otherwise tries minikube for local dev
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config(context="minikube")
        self.namespace = namespace

    def getDeploy(self, deployment_name: str):
        return client.AppsV1Api().read_namespaced_deployment(namespace=self.namespace, name=deployment_name)

    def getReplicas(self, deployment_name: str):
        return (
            client.AppsV1Api().read_namespaced_deployment(namespace=self.namespace, name=deployment_name).spec.replicas
        )

    def isDeployExists(self, deployment_name: str):
        exist = False
        try:
            client.AppsV1Api().read_namespaced_deployment(namespace=self.namespace, name=deployment_name)
            exist = True
        except ApiException:
            exist = False
        return exist

    def scaleDeploy(self, deployment_name: str, replicas: int):
        tmp = {"spec": {"replicas": replicas}}
        return client.AppsV1Api().patch_namespaced_deployment(namespace=self.namespace, name=deployment_name, body=tmp)

    def restarted(self, deployment_name: str):
        # compute selector matching deployment
        selector = self._getSelector(deployment_name)

        # counting restart in init_containers and containers
        restart = 0
        for pod in client.CoreV1Api().list_namespaced_pod(namespace=self.namespace, label_selector=selector).items:
            if not pod.metadata.name.startswith(deployment_name):
                continue
            for c in pod.status.container_statuses:
                restart += c.restart_count
            if pod.status.init_container_statuses:
                for c in pod.status.init_container_statuses:
                    restart += c.restart_count
        return restart > 0

    def waitDeploymentReady(self, deployment_name: str, maxWait=60):
        # this function extract the status from the list of pods, and then compare
        # count the pods not in the “Running” state.
        def fun(pods):
            return len(list(filter(lambda phase: phase != "Running", map(lambda pod: pod.status.phase, pods),)))

        # wait for scale to be active
        print(f"waiting for pod to be created of deployment {deployment_name}")
        while len(self.getPodsList(deployment_name)) == 0:
            time.sleep(1)

        print(f"Waiting for pods of deployment {deployment_name} to run for {maxWait}s")
        i = 0
        while self._iterOnPods(fun, deployment_name) > 0:
            time.sleep(1)
            i += 1
            if i > maxWait:
                print("[KubernetesInterface] Gave up on waiting on {} after {}".format(deployment_name, maxWait))
                return False
        return True if i == 0 else i

    def deploy(self, deploy):
        res = {}
        try:
            if self.isDeployExists(deploy.metadata.name):
                prev = client.AppsV1Api().read_namespaced_deployment(
                    namespace=self.namespace, name=deploy.metadata.name
                )
                deploy.metadata.generation = prev.metadata.generation + 1
                res = client.AppsV1Api().replace_namespaced_deployment(
                    namespace=self.namespace, name=deploy.metadata.name, body=deploy,
                )
            else:
                print(f"Deployment {deploy.metadata.name} doesn't exist: creating it.")
                res = client.AppsV1Api().create_namespaced_deployment(namespace=self.namespace, body=deploy)
        except ApiException as e:
            print(f"exception when trying to create or update {deploy.metadata.name}: {e}")
        return res

    def getPodsList(self, deployment_name: str):
        def fun(pods):
            return list(filter(lambda name: deployment_name in name, map(lambda pod: pod.metadata.name, pods),))

        return self._iterOnPods(fun, deployment_name)

    def _iterOnPods(self, fun, deployment_name: str):
        selector = self._getSelector(deployment_name)
        pods = client.CoreV1Api().list_namespaced_pod(namespace=self.namespace, label_selector=selector).items
        return fun(pods)

    def _getSelector(self, deployment_name: str):
        deployment = client.AppsV1Api().read_namespaced_deployment(namespace=self.namespace, name=deployment_name,)
        selector = ""
        for key in deployment.spec.selector.match_labels:
            selector += key + "=" + deployment.spec.selector.match_labels[key] + ","
        return selector[:-1]
