use clap::Parser;
use std::{net::SocketAddr, path::PathBuf, sync::Arc};
use tokio::signal::unix::SignalKind;
use tokio_util::sync::CancellationToken;

mod auth;
mod logging;
mod filter;
mod vpn;

use auth::http::HttpAuthenticator;
use logging::postgres::PgsqlLogger;
use vpn::Vpn;

#[derive(Debug, Parser)]
#[command(version, about, long_about = None)]
struct Cli {
    /// Interface name for the internal interface which the VPN will be attached to.
    #[arg(required = true)]
    pub interface: String,
    /// Bind address for the VPN.
    #[arg(short, long, default_value = "[::]:9100")]
    pub vpn: SocketAddr,
    /// Bind interface (external) for the VPN.
    #[arg(short, long)]
    pub bind: Option<String>,

    /// Path to network filter definition.
    #[arg(short, long, default_value = "/etc/firewall/filter")]
    pub filter: PathBuf,

    /// Authentication backend.
    #[arg(short, long, default_value = "http://localhost:9101/api/login")]
    pub authentication: String,

    /// User to drop privileges to.
    #[arg(short, long, default_value = "nobody")]
    pub user: String,
    /// Group to drop privileges to.
    #[arg(short, long, default_value = "nogroup")]
    pub group: String,

    /// Database connection for packet logging.
    #[arg(short, long, default_value = "postgresql://anonymous:anonymous@db/firewall")]
    pub db: String,
    /// Database query for packet logging ($1: username, $2: packet data).
    #[arg(short, long, default_value = "SELECT insert_user_log($1, $2)")]
    pub log: String,
    /// Database CA certificate.
    #[arg(short, long, default_value = "/state/firewall/tls/ca.crt")]
    pub ca_certificate: Option<PathBuf>,
}

#[tokio::main]
async fn main() -> std::io::Result<()> {
    tracing_subscriber::fmt::init();
    let args = Cli::parse();

    // The filter backend does the actual firewalling.
    let filter = match filter::parser::from_file(&args.filter) {
        Ok(filter) => filter,
        Err(error) => {
            tracing::error!("Failed to read filter definition from {:?}: {}", args.filter, error);
            return Err(error.into());
        }
    };
    tracing::info!("Loaded filter:\n{filter}");

    // Create the authentication backend
    let authenticator = match HttpAuthenticator::new(args.authentication).await {
        Ok(authenticator) => Arc::new(authenticator),
        Err(error) => {
            tracing::error!("Failed to create authentication backend: {error}");
            return Err(std::io::Error::other(error));
        }
    };

    // Create the logging backend
    let logger = match PgsqlLogger::new(&args.db, args.log, &args.ca_certificate).await {
        Ok(logger) => logger,
        Err(error) => {
            tracing::error!("Failed to create logging backend: {error}");
            return Err(std::io::Error::other(error));
        }
    };

    // NB: On the internal interface, don't _actually_ forward any outbound traffic.
    // Drop it silently to avoid the ICMP spam. If we're interested, the packet socket has seen it.
    // You will want to set the net.ipv{4,6}.conf.$interface.forwarding sysctls to zero.
    let vpn = Vpn::new(args.vpn, args.interface, args.bind, authenticator, logger, filter).await?;

    // Drop privileges now that we have created the necessary sockets.
    // libc synchronizes this across threads.
    let Some(user) = uzers::get_user_by_name(&args.user) else {
        tracing::error!("User {} does not exist, please specify --user", args.user);
        return Err(std::io::Error::other("No such user"));
    };
    let Some(group) = uzers::get_group_by_name(&args.group) else {
        tracing::error!("Group {} does not exist, please specify --group", args.group);
        return Err(std::io::Error::other("No such group"));
    };
    nix::unistd::setgroups(&[])?;
    nix::unistd::setgid(nix::unistd::Gid::from_raw(group.gid()))?;
    nix::unistd::setuid(nix::unistd::Uid::from_raw(user.uid()))?;

    // Run until SIGTERM or SIGINT.
    let mut sigterm = match tokio::signal::unix::signal(SignalKind::terminate()) {
        Ok(signal) => signal,
        Err(error) => {
            tracing::error!("Failed to register SIGTERM handler: {error}");
            return Err(std::io::Error::other(error));
        }
    };

    let token = CancellationToken::new();
    tokio::select! {
        _ = vpn.run(token.clone()) => {
            tracing::info!("VPN stopped, exiting...");
            token.cancel();
        },
        Some(()) = sigterm.recv() => {
            token.cancel();
        },
        result = tokio::signal::ctrl_c() => {
            if let Err(error) = result {
                tracing::error!("Failed to wait for Ctrl+C: {error}");
            }
            token.cancel();
        }
    }

    Ok(())
}
