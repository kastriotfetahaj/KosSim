/// This module implements the individual filter expressions that can be used to match packets.

use bytes::Bytes;
use crate::filter::{conntrack::{State, Track}, packet::{IpVersion, Packet}};
use std::{fmt::{Display, Formatter}, ops::Range};

/// Filter verdict.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Verdict {
    /// Allow the packet through unmodified.
    Allow,
    /// Drop the packet.
    Drop,
}

/// Indicates relative to which layer the matching occurs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum Layer {
    /// L3 (IPv4 / IPv6) network header.
    Network,
    /// L4 (TCP / UDP) transport header.
    Transport,
    /// Payload data.
    Payload,
}

/// Comparison operation on a match.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Comparison {
    /// Equality comparison (must be == to match)
    Equal,
    /// Inequality comparison (must be != to match)
    NotEqual,
}

impl Comparison {
    /// Applies the comparison to two values.
    #[inline(always)]
    pub fn check<T: Eq>(self, a: T, b: T) -> bool {
        match self {
            Comparison::Equal => a == b,
            Comparison::NotEqual => a != b,
        }
    }

    /// Inverts the comparison type.
    pub fn not(self) -> Self {
        match self {
            Comparison::Equal => Comparison::NotEqual,
            Comparison::NotEqual => Comparison::Equal,
        }
    }

    /// Converts the comparison to its filter code representation ("not " for `NotEqual`, the empty
    /// string otherwise).
    fn to_code(&self) -> &'static str {
        match self {
            Comparison::Equal => "",
            Comparison::NotEqual => "not ",
        }
    }
}

/// A filter expression.
#[derive(Clone, Debug)]
pub(crate) enum Expr {
    /// Match a range of bytes in the data.
    Range { layer: Layer, range: Range<usize>, mask: Option<Bytes>, value: Bytes, comparison: Comparison },
    /// Matches on the IP version.
    IpVersion { version: IpVersion, comparison: Comparison },
    /// Matches on the L4 protocol.
    L4Proto { proto: i32, comparison: Comparison },
    /// Matches the L4 destination port.
    L4Dport { port: u16, comparison: Comparison },
    /// Matches the L4 source port.
    L4Sport { port: u16, comparison: Comparison },
    /// Match the connection state.
    State { state: State, comparison: Comparison },
    /// Always perform the given action.
    Always,
    /// Never perform the given action.
    Never,
    /// Matches packets that match any of the given expressions.
    Or { exprs: Vec<Expr> },
    /// Matches packets that match all of the given expressions.
    And { exprs: Vec<Expr> },
}

impl Expr {
    /// Negates the expression, typically by flipping the `Comparison` within.
    pub fn not(self) -> Self {
        match self {
            Expr::Range { layer, range, mask, value, comparison } => Expr::Range { layer, range, mask, value, comparison: comparison.not() },
            Expr::IpVersion { version, comparison } => Expr::IpVersion { version, comparison: comparison.not() },
            Expr::L4Proto { proto, comparison } => Expr::L4Proto { proto, comparison: comparison.not() },
            Expr::L4Dport { port, comparison } => Expr::L4Dport { port, comparison: comparison.not() },
            Expr::L4Sport { port, comparison } => Expr::L4Sport { port, comparison: comparison.not() },
            Expr::State { state, comparison } => Expr::State { state, comparison: comparison.not() },
            Expr::Always => Expr::Never,
            Expr::Never => Expr::Always,
            Expr::Or { exprs } => Expr::And { exprs: exprs.into_iter().map(|e| e.not()).collect() },
            Expr::And { exprs } => Expr::Or { exprs: exprs.into_iter().map(|e| e.not()).collect() },
        }
    }

    /// Evaluates the expression on the given context. `async` only if connection tracking is invoked.
    pub async fn evaluate<C: Packet + Track>(&self, context: &C) -> bool {
        match self {
            Expr::Range { layer, range, comparison, mask, value } => {
                let Some(slice): Option<&[u8]> = match layer {
                    Layer::Network => Some(context.layer_3()),
                    Layer::Transport => context.layer_4().map(|(_, slice)| slice),
                    Layer::Payload => context.layer_5(),
                }.and_then(|slice| slice.get(range.clone())) else {
                    return false;
                };
                if value.len() != slice.len() {
                    tracing::error!("Range expression: value does not match selected range");
                    return false;
                }
                match mask {
                    Some(mask) => {
                        if mask.len() != slice.len() {
                            tracing::error!("Range expression: mask does not match selected range");
                            return false;
                        }
                        match comparison {
                            Comparison::Equal => {
                                for index in 0..slice.len() {
                                    if slice[index] & mask[index] != value[index] {
                                        return false;
                                    }
                                }
                                return true;
                            },
                            Comparison::NotEqual => {
                                for index in 0..slice.len() {
                                    if slice[index] & mask[index] != value[index] {
                                        return true;
                                    }
                                }
                                return false;
                            },
                        }
                    },
                    None => comparison.check(slice, value),
                }
            },
            Expr::IpVersion { version, comparison } => comparison.check(context.ip_version(), Some(*version)),
            Expr::L4Proto { proto, comparison } => comparison.check(context.layer_4().map(|(proto, _)| proto), Some(*proto)),
            Expr::L4Sport { port, comparison } => comparison.check(context.layer_4_ports().map(|p| p.source), Some(*port)),
            Expr::L4Dport { port, comparison } => comparison.check(context.layer_4_ports().map(|p| p.destination), Some(*port)),
            Expr::State { state, comparison } => comparison.check(state, &context.state().await),
            Expr::Always => true,
            Expr::Never => false,
            Expr::Or { exprs } => {
                for expr in exprs.iter() { if Box::pin(expr.evaluate(context)).await { return true; } }
                false
            },
            Expr::And { exprs } => {
                for expr in exprs.iter() { if !Box::pin(expr.evaluate(context)).await { return false; } }
                true
            }
        }
    }
}

impl Display for Expr {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Expr::Range { layer, range, mask, value, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                match layer {
                    Layer::Network => write!(f, "l3"),
                    Layer::Transport => write!(f, "l4"),
                    Layer::Payload => write!(f, "l5"),
                }?;
                write!(f, "offset {}", range.start)?;
                if let Some(bytes) = mask {
                    write!(f, "mask {}", hex::encode(bytes))?;
                }
                write!(f, "{}", hex::encode(value))
            },
            Expr::IpVersion { version, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                match version {
                    IpVersion::V4 => write!(f, "ip"),
                    IpVersion::V6 => write!(f, "ipv6"),
                }
            },
            Expr::L4Proto { proto, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                match *proto {
                    libc::IPPROTO_TCP => write!(f, "tcp"),
                    libc::IPPROTO_UDP => write!(f, "udp"),
                    proto => write!(f, "l4proto {proto}"),
                }
            },
            Expr::L4Dport { port, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                write!(f, "dport {port}")
            },
            Expr::L4Sport { port, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                write!(f, "sport {port}")
            },
            Expr::State { state, comparison } => {
                write!(f, "{}", comparison.to_code())?;
                match state {
                    State::Invalid => write!(f, "state invalid"),
                    State::New => write!(f, "state new"),
                    State::Established => write!(f, "state established"),
                    State::Related => write!(f, "state related"),
                    State::Untracked => write!(f, "state untracked"),
                }
            },
            Expr::Always => Ok(()),
            Expr::Never => write!(f, "never"),
            Expr::Or { exprs } => {
                for (index, expr) in exprs.iter().enumerate() {
                    if index != 0 {
                        write!(f, " || ")?;
                    }
                    match expr {
                        Expr::Or { .. } | Expr::And { .. } => write!(f, "({})", expr)?,
                        _ => expr.fmt(f)?,
                    }
                }
                Ok(())
            },
            Expr::And { exprs } => {
                for (index, expr) in exprs.iter().enumerate() {
                    if index != 0 {
                        write!(f, " && ")?;
                    }
                    match expr {
                        Expr::Or { .. } | Expr::And { .. } => write!(f, "({})", expr)?,
                        _ => expr.fmt(f)?,
                    }
                }
                Ok(())
            },
        }
    }
}
