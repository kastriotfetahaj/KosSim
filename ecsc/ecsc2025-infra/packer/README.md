# Packer Configs for ECSC-Infra
## Usage:
Fill in static.yml and secrets.yml with similar secrets to the original bambictf.
Exec into the container defined in the compose file.

Within the container change into the packer directory \
`packer build <path_to_packer_config>` \
for all images you want to build.
