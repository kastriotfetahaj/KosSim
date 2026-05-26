 Steps to set up a CTF environment

## Choose a Name

Must match: (`[a-z]+[a-z0-9-]*`). Used in several places. In some places it is just a
convention, but you will make your life easier if you stick to it. It's referred to with
`<ctf>` in this guide.

## Prepare a namespace

Create a kubernetes namespace, named equally to the ctf (convention) and use it for all
resources you deploy. It needs to contain several secrets.

| Name                 | Comment                                                  |
|----------------------|----------------------------------------------------------|
| oauth2-proxy-arkime  | OAuth creds, optional dev envs, use kubectl port-forward |
| oauth2-proxy-grafana |                                                          |
| oauth2-proxy-kibana  |                                                          |
| s3-hetzner-elastic   | S3 creds for ES snapshots, optional dev envs             |
| ci-attacking-lab-cr  | ImagePullSecret for ctfroute, arkime, etc.               |

You can easily copy them from an existing namespace if you have `kubectl neat`:

```sh
kubectl -n <existing-ns> get secret <name> -o yaml |       # Get the secret as yaml
kubectl neat | \                                           # Remove unwanted attributes
grep -v namespace | \                                      # Remove ns from yaml
kubectl -n <new-ns> apply -f -                             # Add it to new ns
```

🐟

```sh
for x in oauth2-proxy-arkime oauth2-proxy-grafana oauth2-proxy-kibana s3-hetzner-elastic ci-attacking-lab-cr;
  kubectl -n <src-ns>  get secret $x -o yaml | kubectl neat | grep -v namespace | kubectl -n <dst-ns> apply -f -
end;
```


## Prepare your ctfroute values

Use ctfroute-confgen with `--chart`.

Place the chart config int `k8s/events/<ctf>-ctfroute-values.yaml`.

> [!IMPORTANT]
> Don't forget to add `imagePullSecrets` to the generated chart config.

## Set up tofu vars and spawn vms

Check the [Readme](../tofu/README.md) for instructions on how to set up tofu!

You can copy and adjust one of the existing var files in `tofu/event-vars/`.

> [!IMPORTANT]
> Don't forget to point your tofu vars to the ctfroute values you created in the
> previous step!

```
tofu apply -var-file=event-vars/<your-event-vars>.tfvars`
```

## Install the helm charts in your namespace

See the [charts](../charts) dir. You may want to familiarize yourself with every chart's
`values.yaml`. If you intend to commit your values files, please place them in:

```
k8s/events/<ctf>-ctfroute-values.yaml
k8s/events/<ctf>-arkime-values.yaml
k8s/events/<ctf>-ctf-monitoring-values.yaml
k8s/events/<ctf>-gamserver-values.yaml
```
run `helm install` on all the services you want from the list above
for example `helm install ctfroute charts/ctfroute/ -f k8s/events/<ctf>-ctfroute-values.yaml`

It's fine to skip arkime or ctf-monitoring if you don't need them. You need workers for
arkime or ctf-monitoring and if you use smaller VMs you likely need to adjust the
resource requests in your values.

## Prepare OAuth Clients in Keycloak

These steps require a KC admin: @sinitax or @NiklasBeierl

You need to append `<tool>-<ctf>.gartenverein-tackenberg.de/oauth2/callback` to the
respective `ecsc-<tool>` client's valid redirect urls.

| Tool           | Client       | Redirect url                                                       |
|----------------|--------------|--------------------------------------------------------------------|
| arkime         | ecsc-arkime  | https://arkime-CTFNAME.gartenverein-tackenberg.de/oauth2/callback  |
| kibana (logs)  | ecsc-kibana  | https://kibana-CTFNAME.gartenverein-tackenberg.de/oauth2/callback  |
| grafana (logs) | ecsc-grafana | https://grafana-CTFNAME.gartenverein-tackenberg.de/oauth2/callback |


## Gameserver

The ctfroute chart also creates a service account for the gameserver. After deploying
the chart, create a token for the gameserver:

```
kubectl create token gameserver --duration 4h
```

Afterwards, add the token to the kubernetes config for the gameserver. For that SSH into the gameserver (tofu created a ssh_config for all hosts in ../tofu/generated-config/ssh_config). Go into `cd /srv/gameserver` and `git pull` and make sure you are on the correct branch for the ctf. Then paste the token you create into the `kube.config` and adjust the namespace. You may want to adjust the gameserver settings in config.yaml aswell. 
