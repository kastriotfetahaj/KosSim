# docker compose up --build --force-recreate
# docker compose exec bambictf bash -c \
function builder_pane () {
    echo "$@";
    if ((tmux ls -F "#{session_name}" || true) | grep builder) &> /dev/null; then 
        tmux splitw -h -t builder   -- $@;
    else
        tmux new -s builder -d      -- $@; 
    fi
    return $?;
}

set -ex

. ../.secrets/openrc.sh
(

builder_pane packer build --on-error=ask ovhcloud/ecsc-infra.pkr.hcl
builder_pane packer build --on-error=ask ovhcloud/ecsc-infra-trixie.pkr.hcl
builder_pane packer build --on-error=ask ovhcloud/ecsc-router.pkr.hcl
builder_pane packer build --on-error=ask ovhcloud/ecsc-vulnbox.pkr.hcl

tmux select-layout -t builder even-horizontal
tmux a -t builder

sleep 10

builder_pane packer build --on-error=ask ovhcloud/ecsc-gameserver.pkr.hcl
builder_pane packer build --on-error=ask ovhcloud/ecsc-checker.pkr.hcl
builder_pane packer build --on-error=ask ovhcloud/ecsc-vulnexploiter.pkr.hcl


# packer build --on-error=ask ovhcloud/ecsc-checker-demo.pkr.hcl
# packer build --on-error=ask ovhcloud/ecsc-vulnbox-demo.pkr.hcl

# packer build --on-error=ask ovhcloud/ecsc-checker-cte.pkr.hcl
# packer build --on-error=ask ovhcloud/ecsc-vulnbox-cte.pkr.hcl

# builder_pane packer build --on-error=ask ovhcloud/ecsc-checker-player-demo.pkr.hcl
# builder_pane packer build --on-error=ask ovhcloud/ecsc-vulnbox-player-demo.pkr.hcl


# builder_pane packer build --on-error=ask ovhcloud/ecsc-exploiter.pkr.hcl
tmux select-layout -t builder even-horizontal
tmux a -t builder


)
