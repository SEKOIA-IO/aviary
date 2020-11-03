# deps
from deepdiff import DeepDiff

# std
import math
import time
import copy
import fnmatch
import re
import uuid
import datetime


class BirdWatcher:
    def __init__(self, deployment, config, prom, kube):
        self.baseDeploymentName = deployment  # original deployment name
        self.primaryName = deployment + "-primary"  # primary deployment name
        self.canaryName = deployment + "-canary"  # canary deployment name
        self.replicas = 0  # replicas on original deployment
        self.originalBaseDeployment = {}  # used to watch changes to original deployment
        self.prom = prom  # instance of PrometheusClient
        self.kube = kube

        # admin console flags
        self.bypass_next_deployment = False
        self.abort = False
        self.deploying = False

        self.config = self._convertConfig(config)  # config from canaries.yaml

    def _convertConfig(self, config):
        config["breakpoint"] = int(config["breakpoint"][:-1]) / 100
        config["step"] = int(config["step"][:-1]) / 100
        config["max_step_duration"] = (
            int(config["max_step_duration"][:-1]) * {"s": 1, "m": 60, "h": 3600}[config["max_step_duration"][-1]]
        )
        config["abort"] = int(config["abort"][:-1]) * {"s": 1, "m": 60, "h": 3600}[config["abort"][-1]]
        config["check_success_step_duration"] = (
            int(config["check_success_step_duration"][:-1])
            * {"s": 1, "m": 60, "h": 3600}[config["check_success_step_duration"][-1]]
        )
        config["check_max_failures"] = config.get("check_max_failures", 1)

        if config.get("start_delay"):
            config["start_delay"] = (
                int(config["start_delay"][:-1]) * {"s": 1, "m": 60, "h": 3600}[config["start_delay"][-1]]
            )
        else:
            config["start_delay"] = 0

        # check unbounded value that could lead to ever success of deployment
        m = config["check_max_failures"] * config["check_success_step_duration"]
        if config["max_step_duration"] < m:
            self.warn(
                f"'max_step_duration'({config['max_step_duration']}s) is less than "
                f"'check_max_failures({config['check_max_failures']}) * "
                f"check_success_step_duration({config['check_success_step_duration']}s)' and it shouldn't. "
                f"Adjusting it to {m+1}s",
            )
            config["max_step_duration"] = m + 1
        return config

    def log(self, *args):
        print(f"[{self.baseDeploymentName}]: ", *args)

    def warn(self, *args):
        print(f"[WARN {self.baseDeploymentName}]: ", *args)

    def initCanary(self):
        # To perform a canary deployment, we need :
        # - The original deployment scaled to 0
        # - A copy of the original deployment, the primary
        # - A copy of the new deployment, the canary
        # This checks if this is already set up, and applies it otherwise
        if not self.kube.isDeployExists(self.baseDeploymentName):
            self.log("Couldn't find deployment")
            return False
        deployment = self.kube.getDeploy(self.baseDeploymentName)
        # check if deployment is already ready for the canary setup
        if (
            deployment.spec.replicas == 0
            and self.kube.isDeployExists(self.primaryName)
            and self.kube.isDeployExists(self.canaryName)
        ):
            return self._checkCanaryInit()

        self.replicas = deployment.spec.replicas

        self.log("Creating mirror and canary deployments ...")
        canary = copy.deepcopy(deployment)
        primary = copy.deepcopy(deployment)
        primary.metadata.name = self.primaryName
        self.kube.deploy(self.cleanupDeploy(primary))

        canary.metadata.name = self.canaryName
        canary.spec.replicas = 0
        self.kube.deploy(self.cleanupDeploy(canary))
        # scale base deploy to 0
        self.kube.scaleDeploy(self.baseDeploymentName, 0)
        self.log(
            "All primaries ready after {}s, scaling OG to 0".format(self.kube.waitDeploymentReady(self.primaryName))
        )
        return True

    def _checkCanaryInit(self):
        # We are in init phase, check if leftover canary has been running
        # if it's the case scale primary to canary + primary (risk of having
        # nominal +1 instances). rollback primary to base deploy (if canary
        # exist, may be because failure happened during rollout).
        self.log("Canary setup looks initalized already")
        if self.kube.getReplicas(self.canaryName) != 0:
            self.log("Found leftovers of canary rollout, rolling back to original primary only")
            self.kube.scaleDeploy(
                self.primaryName, self.kube.getReplicas(self.canaryName) + self.kube.getReplicas(self.primaryName),
            )
            self.rollbackBaseDeployment()
            self.kube.scaleDeploy(self.canaryName, 0)
            self.log("done in {}s".format(self.kube.waitDeploymentReady(self.primaryName)))
        # get the goal of wanted replicas from primary deployment
        deployment = self.kube.getDeploy(self.primaryName)
        self.replicas = deployment.spec.replicas
        return True

    def watch(self):
        # This checks changes on the original deployment every 2 seconds,
        # and triggers direct or canary deployment following the output of shouldDeploy
        self.log("Watching changes on OG deployment ...")
        self.originalBaseDeployment = self.kube.getDeploy(self.baseDeploymentName)

        while 1:
            """deployment = self.api.list_namespaced_deployment(
                namespace="sic", field_selector="metadata.name={}".format(service)
            ).items[0]"""
            baseDeployment = self.kube.getDeploy(self.baseDeploymentName)

            if baseDeployment.spec != self.originalBaseDeployment.spec:
                decision = self.shouldDeploy(self.originalBaseDeployment, baseDeployment)
                if decision == "canary":
                    self.deployCanary(baseDeployment)
                elif decision == "direct":
                    self.log("Deploying directly")
                    self.deployDirect(baseDeployment)
                elif decision == "scale":
                    self.log("Scaling primary to {} instances".format(baseDeployment.spec.replicas))
                    self.kube.scaleDeploy(self.baseDeploymentName, 0)
                    self.kube.scaleDeploy(self.primaryName, baseDeployment.spec.replicas)
                    self.replicas = baseDeployment.spec.replicas
                else:
                    self.log("ignoring")
                self.originalBaseDeployment = self.kube.getDeploy(self.baseDeploymentName)
            else:
                time.sleep(1)
            time.sleep(2)
            self.deploying = False

    def shouldDeploy(self, baseDeployment, newDeployment):
        # This tries to decide if an observed change to the original deployment should be deployed directly
        # or using a progressive rollout (canary)
        # No change to the original deployment should be ignored,
        # but some path are just k8s versioning and should not be taken into account (ignorePath)
        if self.bypass_next_deployment:
            self.bypass_next_deployment = False
            self.log("Canary deployment bypassed as configured by admin console")
            return "direct"

        canaryPath = [
            "root._spec._template._spec._containers*",
            "root._spec._template._spec._init_containers*",
        ]  # support glob matching
        ignorePath = [
            "root._metadata._resource_version",
            "root._metadata._generation",
            "root._metadata._annotations._deployment.*",
            "root._status*",
        ]
        scalePath = "root._spec._replicas"

        contains_scale = False  # if scaling the base deployment, report scale on primary and scale down base.
        skip = True  # a flag set to False whenever a meaningful change is detected
        canaryPathRE = [re.compile(fnmatch.translate(cp).replace("[", "\\[").replace("]", "\\]")) for cp in canaryPath]

        ignorePathRE = [re.compile(fnmatch.translate(cp).replace("[", "\\[").replace("]", "\\]")) for cp in ignorePath]

        diff = DeepDiff(baseDeployment, newDeployment)
        values_changed = diff["values_changed"]

        if diff.get("type_changes"):
            values_changed.update(diff["type_changes"])

        for key, changes in values_changed.items():
            # decide if observed change should be ignored
            ignore = False
            for ipathRE in ignorePathRE:
                if ipathRE.match(key):
                    ignore = True
            if ignore:
                continue
            self.log(
                "Saw changes to", key, "({} -> {})".format(changes["old_value"], changes["new_value"]),
            )

            if key == scalePath and changes["new_value"] != 0:  # og deployment was scaled manually
                contains_scale = True
            elif key == scalePath and changes["new_value"] == 0:  # og deployment was rescaled to 0 by aviary, skip
                contains_scale = False
            else:
                skip = False

            for pathRE in canaryPathRE:
                if pathRE.match(key):
                    return "canary"
        if contains_scale and skip:  # skip will always be true if kubectl scale was called on the original deployment
            return "scale"
        return "direct" if not skip else ""

    def prepareDeploy(self, deployment):
        deployment.metadata.annotations["aviary-id"] = str(uuid.uuid4())
        return deployment

    def cleanupDeploy(self, deployment):
        deployment = copy.deepcopy(deployment)
        deployment.metadata.uid = None
        deployment.metadata.self_link = None
        deployment.metadata.generation = 0
        deployment.metadata.creation_timestamp = None
        deployment.metadata.resource_version = None
        deployment = self.prepareDeploy(deployment)
        return deployment

    def deployDirect(self, baseDeployment):
        # handle a direct deployment to the primary deployment, without canary
        # get primary deployment and put the base.spec into primary.spec
        primary = self.kube.getDeploy(self.primaryName)
        primary.spec = baseDeployment.spec

        # scale base deploy to 0 (apply stack raise the scale)
        self.kube.scaleDeploy(self.baseDeploymentName, 0)

        # set primary replicas number to expected value
        primary.spec.replicas = self.replicas
        self.kube.deploy(self.prepareDeploy(primary))

    def deployCanary(self, baseDeployment):
        self.deploying = True
        # handle a canary deployment
        # canaries are scaled up progressively, following the "step" parameter in the configuration
        # final promotion of the canary deployment is performed if the "breakpoint" volume of instance is reached
        # and if every metric listed under "success" returns something
        baseDeployment = copy.deepcopy(baseDeployment)
        self.kube.scaleDeploy(self.baseDeploymentName, 0)
        self.log("Rolling out canary deployment")

        # get canary object and update spec to latest base deployment
        canary = self.kube.getDeploy(self.canaryName)
        canary.spec = baseDeployment.spec
        self.kube.deploy(self.prepareDeploy(canary))

        maxInstances = math.ceil(self.replicas * self.config["breakpoint"])
        stepInstances = math.ceil(self.replicas * self.config["step"])
        canaryInstances = stepInstances
        failed = False
        ts_start = time.time()
        self.log(f"Breakpoint set at {maxInstances} instances, going by increments of {stepInstances}")
        expected_deploy_time = math.ceil(maxInstances / stepInstances) * (
            self.config["start_delay"] + self.config["max_step_duration"]
        )
        expected_deploy_time = str(datetime.timedelta(seconds=expected_deploy_time))

        self.log(f"Expected deployment time is around {expected_deploy_time}s")

        while canaryInstances <= maxInstances and not failed and not self.abort:
            self.log(f"Deploying {stepInstances} instance ... ({canaryInstances}/{self.replicas-canaryInstances})")
            self.kube.scaleDeploy(self.canaryName, canaryInstances)
            if not self.kube.waitDeploymentReady(self.canaryName, self.config["abort"]):
                failed = True
                break
            self.kube.scaleDeploy(self.primaryName, self.replicas - canaryInstances)
            self.kube.waitDeploymentReady(self.primaryName)
            self.log("done")
            canaryInstances += stepInstances

            time.sleep(self.config["start_delay"])

            ts_start = time.time()
            failures = 0
            while time.time() - ts_start < self.config["max_step_duration"]:
                if self.abort:
                    break
                if not self.checkCanarySuccess():
                    failures += 1
                    if failures >= self.config["check_max_failures"]:
                        failed = True
                        break
                time.sleep(self.config["check_success_step_duration"])

        if self.abort:
            self.log(f"Canary deployment was aborted via admin console")
            self.abort = False
            self.rollbackCanary()
            return

        if failed:
            self.log(f"Canary deployment failed after {round(time.time() - ts_start)}s, aborting deploy")
            self.rollbackCanary()
            return

        self.log("Reached breakpoint, canaries were successful. Deploying new primaries ...")
        baseDeployment.metadata.name = self.primaryName
        self.deployDirect(baseDeployment)
        self.kube.scaleDeploy(self.canaryName, 0)
        self.kube.waitDeploymentReady(self.primaryName)
        self.originalBaseDeployment = self.kube.getDeploy(self.baseDeploymentName)
        self.log("done. Safe to exit.")

    def checkCanarySuccess(self):
        # checks if canaries instances are successful
        # successful means no restarts, and values returned from all PromQL expressions under "success"
        if self.kube.restarted(self.canaryName):
            self.log("Saw restarts on canary instances")
            return False
        canaryPods = self.kube.getPodsList(self.canaryName)
        for pod in canaryPods:
            for expr in self.config["success"]:
                queryWithPodName = expr["expr"].replace("<<pod>>", pod)
                value = self.prom.getLastValue(queryWithPodName)
                if value is None:
                    self.log(queryWithPodName, ":", value)
                    return False
        return True

    def rollbackCanary(self):
        # scale primary deploy to base number of replicas and scale down canary
        self.kube.scaleDeploy(self.primaryName, self.replicas)
        self.kube.scaleDeploy(self.canaryName, 0)
        self.kube.waitDeploymentReady(self.primaryName)
        self.rollbackBaseDeployment()
        self.log("rollback done. Safe to exit.")

    def rollbackBaseDeployment(self):
        self.log("Rolling back base deployment from primary deployment")
        base = self.kube.getDeploy(self.baseDeploymentName)
        primary = self.kube.getDeploy(self.primaryName)
        base.spec = primary.spec
        base.spec.replicas = 0
        # retrieve current primary replicas and rollback modifications to base deployment
        # this will allow to reapply modifications later
        self.kube.deploy(base)
        self.originalBaseDeployment = self.kube.getDeploy(self.baseDeploymentName)
