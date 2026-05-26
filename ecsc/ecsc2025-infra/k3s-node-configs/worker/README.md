# CTF-Worker Nodes

These nodes run k8s managed workloads that the "infra hosts" like checkers rely on. For
example: HA-Databases for the gameserver or elasticsearch for checker-logs.

## Labels and Taints

The following labels and taints should be applied to these nodes so workloads get 
scheduled appropriately:

**Labels**:

```yml
node-label:
  - ctfr.attacking-lab.com/role=worker
  - ctfr.attacking-lab.com/ctf=<name-of-ctf>
```

**Taints**:

```yml
node-taint:
  - ctfr.attacking-lab.com/role=worker:NoExecute
  - ctfr.attacking-lab.com/ctf=<name-of-ctf>:NoExecute
```




