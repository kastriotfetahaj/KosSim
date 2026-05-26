#!/usr/bin/env bash

set -eu

if [ $# -eq 0 ]; then
  echo "USAGE: $0 <vulnbox-archive> [<password>]"
  exit 1
fi
ARCHIVE=$(realpath "$1")


# Mount HDD
if [ -d "/mnt/dev" ]; then
  echo 'Drive already mounted'
else
  mount /dev/sda1 /mnt
fi

# Clean disk
cd /mnt
if [ -f "etc/fstab" ]; then
  cp boot/grub/grub.cfg /dev/shm/
  cp etc/fstab /dev/shm/
  cp root/.ssh/authorized_keys /dev/shm || true
fi
find . -maxdepth 1 ! -name . ! -name .. ! -name dev ! -name proc ! -name tmp ! -name run  ! -name sys ! -name 'lost+found' ! -name '*.tar.xz' ! -name '*.gpg' ! -name '*.sh' -exec rm -rf {} +
echo "Disk is wiped."

# Unpack to disk
if [[ "$1" == *.gpg ]]; then
  if [ $# -eq 1 ]; then
    echo "USAGE: $0 <vulnbox-archive> <password>"
    exit 1
  fi
  echo 'Unpacking with password ...'
  echo "$2" | gpg --batch --passphrase-fd 0 -d "$ARCHIVE" | xz -d -T0 | tar --xattrs -xp
else
  echo 'Unpacking without password ...'
  tar --xattrs -xpf "$ARCHIVE"
fi
cp /dev/shm/grub.cfg boot/grub/
mv etc/fstab etc/fstab.bak
cp /dev/shm/fstab etc/
sed -n '/# service mounts/,$p' etc/fstab.bak >> etc/fstab
rm etc/fstab.bak
cat /dev/shm/authorized_keys >> root/.ssh/authorized_keys || true


# Repair grub
echo "Repairing grub"
mount -o bind /dev /mnt/dev
mount -o bind /dev/shm /mnt/dev/shm
mount -o bind /run /mnt/run
mount -o bind /sys /mnt/sys
mount -o bind /tmp /mnt/tmp
mount -t proc /proc /mnt/proc
chroot /mnt grub-install /dev/sda
chroot /mnt update-initramfs -u
chroot /mnt update-grub


echo "Done!"
echo "Now insert your SSH key into   >> /mnt/root/.ssh/authorized_keys <<   and reboot"
