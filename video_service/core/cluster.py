import os
import json
import logging
import time
import threading
import httpx
from typing import Dict, Optional, Any, Tuple

logger = logging.getLogger("video_service.core.cluster")

class ClusterConfig:
    def __init__(self, config_path: str = "cluster_config.json"):
        self.self_name = os.environ.get("NODE_NAME", "node-a")
        self.nodes: Dict[str, str] = {}
        self.health_check_interval = 5
        self.internal_timeout = 5
        self.enabled = False
        self.node_status: Dict[str, bool] = {}
        self.last_rr_index = 0
        
        self.load_config(config_path)
        
        if self.enabled:
            self._health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
            self._health_thread.start()

    def load_config(self, config_path: str):
        if not os.path.exists(config_path):
            # Single-node mode — register self only
            self.nodes = {self.self_name: "http://localhost:8000"}
            self.node_status = {self.self_name: True}
            logger.info("cluster: no config file found — single-node mode (node=%s)", self.self_name)
            return

        # ── Parse ──────────────────────────────────────────────────────────
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            logger.error("cluster: config file %s is not valid JSON: %s", config_path, exc)
            self.enabled = False
            self.nodes = {self.self_name: "http://localhost:8000"}
            self.node_status = {self.self_name: True}
            return
        except OSError as exc:
            logger.error("cluster: cannot read config file %s: %s", config_path, exc)
            self.enabled = False
            return

        # ── Validate schema ────────────────────────────────────────────────
        errors: list[str] = []

        nodes = data.get("nodes")
        if not isinstance(nodes, dict) or not nodes:
            errors.append("'nodes' must be a non-empty dict mapping node-name → URL")

        if nodes:
            for name, url in nodes.items():
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    errors.append(f"node '{name}': URL must start with http:// or https:// (got {url!r})")

        if errors:
            for e in errors:
                logger.error("cluster config validation error: %s", e)
            logger.error(
                "cluster: %d validation error(s) in %s — cluster disabled",
                len(errors), config_path
            )
            self.enabled = False
            self.nodes = {self.self_name: "http://localhost:8000"}
            self.node_status = {self.self_name: True}
            return

        # ── Apply ──────────────────────────────────────────────────────────
        cfg_self = data.get("self_name", self.self_name)
        env_name = os.environ.get("NODE_NAME")
        if env_name and cfg_self != env_name:
            logger.warning(
                "cluster: NODE_NAME env=%r overrides config self_name=%r",
                env_name, cfg_self,
            )
            self.self_name = env_name
        else:
            self.self_name = cfg_self

        self.nodes = nodes
        self.health_check_interval = data.get("health_check_interval_seconds", 5)
        self.internal_timeout = data.get("internal_request_timeout_seconds", 5)
        self.enabled = len(self.nodes) > 1

        if self.self_name not in self.nodes:
            logger.warning(
                "cluster: self_name=%r not found in nodes map — adding with default URL",
                self.self_name,
            )
            self.nodes[self.self_name] = "http://localhost:8000"

        for node in self.nodes:
            self.node_status[node] = True

        logger.info(
            "cluster: loaded %s — enabled=%s self=%s nodes=%s",
            config_path, self.enabled, self.self_name, list(self.nodes.keys()),
        )

    def _health_check_loop(self):
        while True:
            for name, url in self.nodes.items():
                if name == self.self_name:
                    self.node_status[name] = True
                    continue
                try:
                    res = httpx.get(f"{url}/health?internal=1", timeout=2.0)
                    self.node_status[name] = res.status_code == 200
                except httpx.RequestError:
                    self.node_status[name] = False
                except Exception:
                    self.node_status[name] = False
            time.sleep(self.health_check_interval)

    def get_healthy_nodes(self) -> list:
        return [node for node, healthy in self.node_status.items() if healthy]

    def select_rr_node(self) -> Optional[str]:
        if not self.enabled:
            return self.self_name
            
        healthy = self.get_healthy_nodes()
        if not healthy:
            return None
            
        self.last_rr_index = (self.last_rr_index + 1) % len(healthy)
        return healthy[self.last_rr_index]

    def get_node_url(self, node_name: str) -> Optional[str]:
        return self.nodes.get(node_name)

_config_path = os.environ.get("CLUSTER_CONFIG", "cluster_config.json")
cluster = ClusterConfig(config_path=_config_path)
