# Routing rules

- POST /jobs/* : ingress node selects a healthy target via round-robin; proxies if target != self.
- GET /jobs/{id}*, DELETE /jobs/{id} : proxy to owner node based on id prefix.
- internal=1 disables re-routing to prevent loops.
