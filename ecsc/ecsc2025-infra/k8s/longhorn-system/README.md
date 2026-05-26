# Longhorn


## S3 backups to hetzner

### Creating the secret:

```sh
kubectl create secret -n longhorn-system generic hetzner-longhorn-backups \ 
--from-literal=AWS_ENDPOINTS=hel1.your-objectstorage.com \ 
--from-literal=AWS_ACCESS_KEY_ID=... \
--from-literal=AWS_SECRET_ACCESS_KEY=...
```

### In Longhorn UI:

Configure the default backup target.  
URL: `s3://b39k36-attacking-lab-longhorn-backups@eu-central/`  
Secret: `hetzner-longhorn-backups`  
