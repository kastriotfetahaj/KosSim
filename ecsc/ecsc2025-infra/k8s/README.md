> [!IMPORTANT]
> This information is not entirely up2date anymore

# Core vs. Router Nodes

### Routers

Routers are deployed as k3s-agents. A template for the config can be found at:
[nodes/routers/config.yaml](nodes/routers/config.yaml).

Notice the following taints and labes:

Taints:

- `ctfr.attacking-lab.com/role=router:NoExecute`
- `ctfr.attacking-lab.com/ctf=<environment>:NoExecute`

Labels:

- `ctfr.attacking-lab.com/role=router`
- `ctfr.attacking-lab.com/ctf=<environment>`

Normal workloads don't have tolerations for these taints, so they don't get
scheduled onto these nodes. The values of the cilium chart were also adjusted to remove
the tolerations for "any" taint, so cilium doesn't run on these nodes.

### Core

For our "core" nodes (control plane and monitoring) we additionally add the label
`ctfr.attacking-lab.com/role=core`. This is also used as a `nodeSelector` for some
workloads such as traefik. Only these nodes can be used for accessing grafana etc.

# Manually provisioned secrets

| Namespace       | Secret Name          | Purpose                                   |
|-----------------|----------------------|-------------------------------------------|
| cert-manager    | hetzner-token        | Token for Hetzner DNS (wildcard certs)    |
| ecsc-staging    | ci-attacking-lab-cr  | PullSecret for Routers (ctfroute)         |
| kube-prometheus | oauth2-proxy-grafana | Oauth2 Proxy Secrets for exposing grafana |

### hetzner-token secret

```sh
kubectl -n cert-manager create secret generic hetzner-secret 
--from-literal=api-key=...
```

### Oauth Proxy Secrets

```sh
kubectl create secret generic oauth2-proxy-<thing> \
  --from-literal=client-id=... \ 
  --from-literal=client-secret=... \ 
  --from-literal=cookie-secret=...  
```
