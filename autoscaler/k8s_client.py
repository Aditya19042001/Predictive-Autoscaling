"""
k8s_client.py
-------------
Kubernetes API wrapper — all cluster interaction lives here.

Two auth modes:
  In-cluster (default):   load_incluster_config()
    Used when the autoscaler runs as a pod. The service account token and
    CA bundle are mounted automatically at well-known paths.

  Out-of-cluster (local dev):  load_kube_config()
    Falls back to ~/.kube/config when not running inside a pod.
    Allows running the autoscaler locally against a minikube cluster.

The autoscaler only needs TWO Kubernetes API calls:
  1. read_namespaced_deployment         — get current replica count
  2. patch_namespaced_deployment_scale  — set new replica count

RBAC required (see k8s/autoscaler/cluster-role.yaml):
  apiGroups: ["apps"]
  resources: ["deployments", "deployments/scale"]
  verbs: ["get", "patch"]
"""

import logging
import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from autoscaler.config import Config

logger = logging.getLogger(__name__)


class KubernetesClient:
    def __init__(self, cfg: Config):
        self._namespace = cfg.namespace
        self._configure_auth()
        self._apps_v1 = client.AppsV1Api()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_current_replicas(self, deployment_name: str) -> int:
        """
        Return the current .spec.replicas for a deployment.

        Returns -1 if the deployment cannot be found or the API is unreachable,
        so the caller can skip this cycle rather than crash.
        """
        try:
            dep = self._apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self._namespace,
            )
            replicas = dep.spec.replicas
            logger.debug(
                "Deployment %s/%s has %d replicas",
                self._namespace, deployment_name, replicas,
            )
            return replicas or 0
        except ApiException as exc:
            logger.error(
                "Failed to read deployment %s: HTTP %s — %s",
                deployment_name, exc.status, exc.reason,
            )
            return -1

    def scale_deployment(self, deployment_name: str, replicas: int) -> bool:
        """
        Patch the replica count of a deployment.

        Uses a strategic merge patch on the /scale subresource — the
        smallest possible payload, avoids touching any other deployment spec.

        Returns True on success, False on failure.
        """
        body = {"spec": {"replicas": replicas}}
        try:
            self._apps_v1.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=self._namespace,
                body=body,
            )
            logger.info(
                "Patched %s/%s → %d replicas",
                self._namespace, deployment_name, replicas,
            )
            return True
        except ApiException as exc:
            logger.error(
                "Failed to scale deployment %s to %d: HTTP %s — %s",
                deployment_name, replicas, exc.status, exc.reason,
            )
            return False

    def deployment_exists(self, deployment_name: str) -> bool:
        """Lightweight pre-flight check before the control loop starts."""
        try:
            self._apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self._namespace,
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                logger.error(
                    "Deployment %s not found in namespace %s",
                    deployment_name, self._namespace,
                )
            else:
                logger.error("Kubernetes API error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _configure_auth():
        """
        Try in-cluster config first (running as a pod).
        Fall back to kubeconfig for local development.
        """
        try:
            config.load_incluster_config()
            logger.info("Kubernetes auth: in-cluster config loaded")
        except config.ConfigException:
            kubeconfig = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
            config.load_kube_config(config_file=kubeconfig)
            logger.info("Kubernetes auth: kubeconfig loaded from %s", kubeconfig)
