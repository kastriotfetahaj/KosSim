#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <unistd.h>
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <string.h>
#include <linux/limits.h>

#include <sys/wait.h>

#include <sys/socket.h>
#include <linux/filter.h>
#include <linux/seccomp.h>

#include <linux/prctl.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/ioctl.h>

#include <time.h>
#include <poll.h>

#define MAX_TOTAL_WRITE_SIZE (2 * 1024 * 1024) // 2 MiB should be enough

static int send_fd(int sock, int fd)
{
	struct msghdr msg = {};
	struct cmsghdr *cmsg;
	char buf[CMSG_SPACE(sizeof(int))] = {0}, c = 'c';
	struct iovec io = {
		.iov_base = &c,
		.iov_len = 1,
	};

	msg.msg_iov = &io;
	msg.msg_iovlen = 1;
	msg.msg_control = buf;
	msg.msg_controllen = sizeof(buf);
	cmsg = CMSG_FIRSTHDR(&msg);
	cmsg->cmsg_level = SOL_SOCKET;
	cmsg->cmsg_type = SCM_RIGHTS;
	cmsg->cmsg_len = CMSG_LEN(sizeof(int));
	*((int *)CMSG_DATA(cmsg)) = fd;
	msg.msg_controllen = cmsg->cmsg_len;

	if (sendmsg(sock, &msg, 0) < 0) {
		perror("sendmsg");
		return -1;
	}

	return 0;
}

static int recv_fd(int sock)
{
	struct msghdr msg = {};
	struct cmsghdr *cmsg;
	char buf[CMSG_SPACE(sizeof(int))] = {0}, c = 'd';
	struct iovec io = {
		.iov_base = &c,
		.iov_len = 1,
	};

	msg.msg_iov = &io;
	msg.msg_iovlen = 1;
	msg.msg_control = buf;
	msg.msg_controllen = sizeof(buf);

	if (recvmsg(sock, &msg, 0) < 0) {
		perror("recvmsg");
		return -1;
	}

	cmsg = CMSG_FIRSTHDR(&msg);

	if (!cmsg) {
		fprintf(stderr, "No cmsg\n");
		return -1;
	}

	return *((int *)CMSG_DATA(cmsg));
}

static int install_syscall_filter(void)
{
	struct sock_filter filter[] = {
		// load system call number
		BPF_STMT(BPF_LD+BPF_W+BPF_ABS, offsetof(struct seccomp_data, nr)),

		// disallowed syscalls (just for safety, shouldn't be used by git)
		BPF_JUMP(BPF_JMP+BPF_JEQ+BPF_K, __NR_pwrite64, 3, 0),
		BPF_JUMP(BPF_JMP+BPF_JEQ+BPF_K, __NR_writev, 2, 0),
		BPF_JUMP(BPF_JMP+BPF_JEQ+BPF_K, __NR_pwritev, 1, 0),
		BPF_JUMP(BPF_JMP+BPF_JEQ+BPF_K, __NR_pwritev2, 0, 1),
		// if any of these match, report system call as unavailable
		// hopefully the libc will then use the normal write one
		BPF_STMT(BPF_RET+BPF_K, SECCOMP_RET_ERRNO | (ENOSYS & SECCOMP_RET_DATA)),

		// intercept write syscall
		BPF_JUMP(BPF_JMP+BPF_JEQ+BPF_K, __NR_write, 0, 1),
		BPF_STMT(BPF_RET+BPF_K, SECCOMP_RET_USER_NOTIF),

		// by default allow all
		BPF_STMT(BPF_RET+BPF_K, SECCOMP_RET_ALLOW)
	};
	struct sock_fprog prog = {
		.len = sizeof(filter) / sizeof(*filter),
		.filter = filter,
	};

	if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) {
		perror("prctl");
		return -1;
	}

	int fd = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_NEW_LISTENER, &prog);
	if (fd < 0) {
		perror("seccomp");
		return -1;
	}
	return fd;
}

void serve_seccomp(int fd) {
	size_t total_write_size = 0;
	while (42) {
		struct seccomp_notif req = {};
		struct seccomp_notif_resp resp = {};

		struct pollfd fdset = {
			.fd = fd,
			.events = POLLIN | POLLHUP,
			.revents = 0,
		};
		if (poll(&fdset, 1, -1) < 0) {
			perror("poll");
			return;
		}
		if (fdset.revents & POLLHUP) {
			fprintf(stderr, "git exited\n");
			return;
		}

		assert(fdset.revents == POLLIN);

		/* fprintf(stderr, "Before notif recv - %ld\n", time(NULL)); */
		if (ioctl(fd, SECCOMP_IOCTL_NOTIF_RECV, &req)) {
			// process probably exited
			fprintf(stderr, "Failed to notif recv\n");
			return;
		}

		resp.id = req.id;
		resp.val = 0;
		resp.error = 0;
		resp.flags = 0;

		assert (req.data.nr == __NR_write);

		assert (SIZE_MAX - total_write_size > req.data.args[2]);

		char path[PATH_MAX] = {};
		snprintf(path, sizeof(path), "/proc/%d/fd/%lld", req.pid, req.data.args[0]);
		char link[PATH_MAX] = {};
		ssize_t len = readlink(path, link, sizeof(link) - 1);
		if (len < 0) {
			perror("readlink");
			kill(req.pid, SIGKILL);
			continue;
		}
		link[len] = '\0';

		if (link[0] == '/' && strncmp(link, "/dev/", 5) != 0) {
			// only count when it writes to file
			total_write_size += req.data.args[2];
			// fprintf(stderr, "Written: %lx (total: %lx / %x)\n", req.data.args[2], total_write_size, MAX_TOTAL_WRITE_SIZE);
		}
			
		if (total_write_size <= MAX_TOTAL_WRITE_SIZE) {
			resp.flags = SECCOMP_USER_NOTIF_FLAG_CONTINUE;
		} else {
			fprintf(stderr, "Size limit reached!\n");
			resp.error = ENOSPC;
			kill(req.pid, SIGKILL);
		}

		if (ioctl(fd, SECCOMP_IOCTL_NOTIF_SEND, &resp)) {
			// process probably exited
			fprintf(stderr, "ioctl_notif_send failed: %d\n", errno);
			continue;
		}
	}
}

int main(int argc, char *argv[])
{
	if (argc < 2) {
		fprintf(stderr, "Usage: seccomp-git-wrapper <command> [args...]\n");
		return 2;
	}
	

	// channel to send seccomp fd over
	int sk_pair[2];
	if (socketpair(PF_LOCAL, SOCK_SEQPACKET, 0, sk_pair) < 0) {
		perror("socketpair");
		return 1;
	}

	pid_t pid = fork();
	if (pid == 0) {
		// child
		int fd = install_syscall_filter();
		if (fd < 0)
			return 1;
		if (send_fd(sk_pair[0], fd) < 0)
			return 1;
		close(fd);
		close(sk_pair[0]);
		close(sk_pair[1]);
		execvp(argv[1], &argv[1]);
		perror("execvp");
		return 1;
	} else if (pid < 0) {
		// error
		perror("fork");
		return 1;
	} else {
		int fd = recv_fd(sk_pair[1]);
		close(sk_pair[0]);
		close(sk_pair[1]);

		if (fd < 0) {
			fprintf(stderr, "Failed to read seccomp fd\n");
			return 1;
		}

		serve_seccomp(fd);
		int status;
		waitpid(pid, &status, 0);
		return status;
	}
}
