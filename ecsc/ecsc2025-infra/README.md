> [!NOTE]
> The state published here primarily serves to satisfy your curiosity.<br>
> The documentation provided is instructive, but limited.

# ECSC 2025 Infrastructure

Infrastructure as code for deploying and managing the ECSC 2025 A/D CTF.

## Architecture

The infrastructure is built on Kubernetes (k3s) and uses a multi-layered network design:

- **Team Networks**: Isolated virtual networks for each competing team
- **Router Mesh**: High-performance wireguard mesh connecting team endpoints
- **Infra Network**: Hosts checkers, submitters, and game servers
- **Overlay Network**: Monitoring and management access to routers

See [docs/ALANA.md](docs/ALANA.md) for detailed network architecture.

## Components

### Infrastructure Provisioning
- **packer/**: VM image builds for Hetzner and OVHcloud
- **tofu2/**: OpenTofu configurations for VM and network provisioning
- **k3s-node-configs/**: Node setup and role definitions for Kubernetes

### Kubernetes / Helm Charts
- **charts/ctfroute**: Core routing infrastructure for team connectivity
- **charts/arkime**: Packet capture and network traffic analysis
- **charts/ctf-monitoring**: Prometheus/Grafana monitoring stack
- **charts/gameserver**: CTF game server deployment
- **charts/logs**: Elasticsearch/Kibana logging stack

### Configuration & Documentation
- **docker/**: Build environment with Packer, Terraform, and Ansible
- **docs/**: Architecture diagrams and setup guides
- **k8s/**: Kubernetes manifests and event configurations

