# Types of nodes or Node "roles"

We distinguish nodes based on the workloads they should handle. In kubernetes, this
manifests as node labels and taints. There is the `ctfr.attacking-lab.com/role`
label, and an equally named taint. We distinguish between:

`core` nodes, whose lifecycle and workloads are not tied to s specific ctf.

`worker` nodes, that are used for "normal" workloads for a specific ctf such as HA
databases or elasticsearch / kibana / prometheus.

`router` nodes, which handle the special router workload (ctf-route) and arkime.

## Where cluster components run

`router` nodes are excluded from running longhorn and cilium. `worker` and `core` nodes
generally run all cluster components.

# Node-level requirements

Some of the cluster components we have in our cluster have Node-level requirements, i.e.
software that needs to be provisioned on the nodes themselves. Not all cluster
components run on all types of nodes.

## Nodes running longhorn

See the requirements listed here:
https://longhorn.io/docs/1.9.1/deploy/install/#installation-requirements

# CTFs / Environments

`worker` and `router` nodes are additionally labelled and tainted with the specific CTF
that they are used for. A CTF can be considered an "environment" (as in dev vs.
staging vs. prod) if you want to stick to traditional software-engineering terms.

The label / taint key is: `ctfr.attacking-lab.com/ctf`.

When provisioning nodes it's important to taint and label them appropriately. For
Workloads the tolerations and nodeSelectors need to be set so appropriately. 
