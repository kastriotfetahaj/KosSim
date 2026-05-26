/// The packet filtering implementation.

use bytes::Bytes;
use std::fmt::{Display, Formatter};

pub(crate) mod conntrack;
pub(crate) mod packet;
pub(crate) mod parser;
mod context;
mod expr;

pub(crate) use expr::Verdict;

use conntrack::{Table, Track};
use context::Context;
use expr::Expr;
use packet::Packet;

/// A filter rule.
#[derive(Clone, Debug)]
pub(crate) struct Rule {
    pub expr: expr::Expr,
    pub action: Action,
}

/// A filter action.
#[derive(Clone, Debug)]
pub(crate) enum Action {
    /// Make a final decision on this packet.
    Final(Verdict),
    /// Run the packet through the specified sub-chain.
    Chain(Vec<Rule>),
    /// Special handling for connection tracking.
    Track(String, Vec<String>),
}

/// A rule or set of rules that can be applied to a filter context.
#[async_trait::async_trait]
trait RuleSet {
    /// Apply the rule to the given filter context.
    async fn apply<C: Packet + Sync + Track>(&self, context: &C) -> Option<Verdict>;
    /// Format the rule (prettified, with the given indentation).
    fn fmt_pretty(&self, f: &mut Formatter<'_>, indent: &str) -> std::fmt::Result;
}

#[async_trait::async_trait]
impl RuleSet for Rule {
    async fn apply<C: Packet + Sync + Track>(&self, context: &C) -> Option<Verdict> {
        if !self.expr.evaluate(context).await {
            #[cfg(feature = "filter-trace")]
            tracing::trace!(
                "'{}' does not match {:?} ({} => {})",
                self.expr,
                Bytes::copy_from_slice(context.layer_3()),
                match context.layer_4_source() { Some(peer) => format!("{peer}"), None => format!("?") },
                match context.layer_4_destination() { Some(peer) => format!("{peer}"), None => format!("?") },
            );
            return None; // No match, no verdict.
        }
        #[cfg(feature = "filter-trace")]
        tracing::trace!(
            "'{}' matches {:?} ({} => {}), action is {}",
            self.expr,
            Bytes::copy_from_slice(context.layer_3()),
            match context.layer_4_source() { Some(peer) => format!("{peer}"), None => format!("?") },
            match context.layer_4_destination() { Some(peer) => format!("{peer}"), None => format!("?") },
            match &self.action {
                Action::Final(Verdict::Allow) => format!("allow"),
                Action::Final(Verdict::Drop) => format!("drop"),
                Action::Chain(_) => format!("nested chain"),
                Action::Track(what, _) => format!("track \"{what}\""),
            },
        );
        match &self.action {
            Action::Final(verdict) => Some(*verdict), // Final verdict has been decided, return it.
            Action::Chain(rules) => rules.apply(context).await, // Forward to this sub-chain.
            Action::Track(what, args) => {
                // Apply special tracking rule, but do not render a verdict.
                context.track(&what, &args[..]).await;
                None
            },
        }
    }

    fn fmt_pretty(&self, f: &mut Formatter<'_>, indent: &str) -> std::fmt::Result {
        write!(f, "{}", indent)?;
        match self.expr {
            Expr::Always => (),
            _ => write!(f, "{} ", self.expr)?,
        };
        match &self.action {
            Action::Final(Verdict::Allow) => write!(f, "allow\n"),
            Action::Final(Verdict::Drop) => write!(f, "drop\n"),
            Action::Chain(rules) => {
                write!(f, "{{\n")?;
                rules.fmt_pretty(f, &format!("{indent}  "))?;
                write!(f, "{indent}}}\n")
            },
            Action::Track(what, args) => {
                if args.is_empty() {
                    write!(f, "track \"{what}\"\n")
                } else {
                    let arg_string = args.join("\", \"");
                    write!(f, "track \"{what}\" for (\"{arg_string}\")\n")
                }
            }
        }
    }
}

#[async_trait::async_trait]
impl RuleSet for Vec<Rule> {
    async fn apply<C: Packet + Sync + Track>(&self, context: &C) -> Option<Verdict> {
        for rule in self.iter() {
            if let Some(verdict) = rule.apply(context).await {
                return Some(verdict);
            }
        }
        None
    }

    fn fmt_pretty(&self, f: &mut Formatter<'_>, indent: &str) -> std::fmt::Result {
        for rule in self.iter() {
            rule.fmt_pretty(f, indent)?;
        }
        Ok(())
    }
}

/// A filter is a set of rules.
#[derive(Clone)]
pub(crate) struct Filter {
    rules: Vec<Rule>,
}

impl Filter {
    pub async fn apply(&self, packet: &mut Bytes, table: Table) -> Verdict {
        let context = Context::new(packet.as_ref(), table);
        let verdict = match self.rules.apply(&context).await {
            Some(verdict) => verdict,
            None => {
                tracing::warn!("Packet {packet:?} did not receive filter verdict, dropping.");
                Verdict::Drop
            }
        };
        #[cfg(feature = "filter-trace")]
        tracing::trace!("Final verdict for {packet:?} is {verdict:?}");
        verdict
    }
}

impl Display for Filter {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        self.rules.fmt_pretty(f, "")
    }
}
