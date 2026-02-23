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
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                self.self_name = data.get("self_name", self.self_name)
                self.nodes = data.get("nodes", {self.self_name: f"http://localhost:8000"})
                self.health_check_interval = data.get("health_check_interval_seconds", 5)
                self.internal_timeout = data.get("internal_request_timeout_seconds", 5)
                self.enabled = len(self.nodes) > 1
                
                for node in self.nodes:
                    self.node_status[node] = True
                    
                logger.info(f"Cluster enabled: {self.enabled}, Self: {self.self_name}, Nodes: {len(self.nodes)}")
            except Exception as e:
                logger.error(f"Failed to load cluster config: {e}")
                self.enabled = False
        else:
            self.nodes = {self.self_name: "http://localhost:8000"}
            self.node_status = {self.self_name: True}

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

cluster = ClusterConfig()
