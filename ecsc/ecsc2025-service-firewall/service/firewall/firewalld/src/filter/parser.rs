/// Parses filter expressions from strings. This should give you a reasonably convenient way to
/// update filters through the API, without recompiling.

use bytes::Bytes;
use chumsky::prelude::*;
use crate::filter::{
    conntrack::State, expr::{Comparison, Expr, Layer, Verdict},
    packet::IpVersion, Action, Filter, Rule,
};
use std::{ops::Range, path::Path};

/// Configuration for a `range` query on packet bytes. Later inlined into `expr::Expr::Range`.
#[derive(Clone, Debug)]
struct RangeSpec {
    layer: Layer,
    range: Range<usize>,
    mask: Option<Bytes>,
    value: Bytes
}

impl RangeSpec {
    fn default_for(value: Vec<u8>) -> Self {
        Self {
            layer: Layer::Network,
            range: 0..value.len(),
            mask: None,
            value: value.into(),
        }
    }
}

/// An AST node for expressions. Reasonably close to `expr::Expr`, but still with the binary tree
/// structure for `Or`/`And`, and with a top-level `Negate` entry that we inline in the actual
/// `expr::Expr`.
#[derive(Clone, Debug)]
enum ExprAstNode {
    IpVersion(IpVersion),
    State(State),
    Protocol(i32),
    Dport(u16),
    Sport(u16),
    Port(u16),
    Range(RangeSpec),
    Negate(Box<ExprAstNode>),
    Or(Box<ExprAstNode>, Box<ExprAstNode>),
    And(Box<ExprAstNode>, Box<ExprAstNode>),
}

impl Into<Expr> for ExprAstNode {
    /// Turn this AST node into its corresponding `Expr`.
    fn into(self) -> Expr {
        let comparison = Comparison::Equal;
        match self {
            ExprAstNode::IpVersion(version) => Expr::IpVersion { version, comparison },
            ExprAstNode::State(state) => Expr::State { state, comparison },
            ExprAstNode::Protocol(proto) => Expr::L4Proto { proto, comparison },
            ExprAstNode::Dport(port) => Expr::L4Dport { port, comparison },
            ExprAstNode::Sport(port) => Expr::L4Sport { port, comparison },
            ExprAstNode::Port(port) => Expr::Or { exprs: vec![
                Expr::L4Dport { port, comparison },
                Expr::L4Sport { port, comparison },
            ] },
            ExprAstNode::Range(spec) => Expr::Range {
                layer: spec.layer,
                range: spec.range,
                mask: spec.mask,
                value: spec.value,
                comparison
            },
            ExprAstNode::Negate(node) => {
                let expr: Expr  = (*node).into();
                expr.not()
            },
            // The parser recurses into lhs, with rhs as the individual Exprs.
            ExprAstNode::Or(lhs, rhs) => {
                let lhs: Expr = (*lhs).into();
                let rhs: Expr = (*rhs).into();
                if let Expr::Or { mut exprs } = lhs {
                    exprs.push(rhs);
                    Expr::Or { exprs }
                } else {
                    Expr::Or { exprs: vec![lhs, rhs] }
                }
            },
            ExprAstNode::And(lhs, rhs) => {
                let lhs: Expr = (*lhs).into();
                let rhs: Expr = (*rhs).into();
                if let Expr::And { mut exprs } = lhs {
                    exprs.push(rhs);
                    Expr::And { exprs }
                } else {
                    Expr::And { exprs: vec![lhs, rhs] }
                }
            },
        }
    }
}

/// Builds the actual parser. See the chumsky documentation for details on how this works.
fn parser<'src>() -> impl Parser<'src, &'src str, Vec<Rule>, extra::Err<Rich<'src, char>>> {
    recursive(|rules| {
        let expr = recursive(|expr| {
            let port_number = text::int(10).to_slice().from_str().unwrapped().padded();
            let protocol = text::int(10).to_slice().from_str().unwrapped().padded();
            let hex_string = one_of("0123456789abcdefABCDEF").repeated().to_slice()
                .try_map(|s: &str, span|
                    hex::decode(s)
                    .map_err(|e| Rich::custom(span, format!("{s} is not a valid hex string: {e}")))
                ).padded();

            let state = choice((
                text::keyword("invalid").padded().to(State::Invalid),
                text::keyword("new").padded().to(State::New),
                text::keyword("established").padded().to(State::Established),
                text::keyword("related").padded().to(State::Related),
                text::keyword("untracked").padded().to(State::Untracked),
            ));

            // range [l3|l4|l5] [offset 123] [mask deadbeef] 12345678
            let range_mask = text::keyword("mask").padded()
                .ignore_then(hex_string.clone())
                .or_not()
                .then(hex_string.map(RangeSpec::default_for))
                .map(|(mask, mut spec)| { spec.mask = mask.map(|m| m.into()); spec });
            let range_offset = text::keyword("offset").padded()
                .ignore_then(text::int(10).to_slice().from_str().unwrapped().padded())
                .or_not()
                .then(range_mask)
                .map(|(offset, mut spec)| {
                    if let Some(offset) = offset {
                        spec.range = offset..(offset + spec.value.len());
                    }
                    spec
                });
            let range = choice((
                text::keyword("l3").padded().to(Layer::Network),
                text::keyword("l4").padded().to(Layer::Transport),
                text::keyword("l5").padded().to(Layer::Payload),
            )).or_not().then(range_offset).map(|(layer, mut spec)| {
                spec.layer = layer.unwrap_or(Layer::Network);
                spec
            }).boxed();

            let simple = choice((
                expr.delimited_by(just('('), just(')')).padded(),
                text::keyword("ip").padded().to(ExprAstNode::IpVersion(IpVersion::V4)),
                text::keyword("ipv6").padded().to(ExprAstNode::IpVersion(IpVersion::V6)),
                text::keyword("dport").padded().ignore_then(port_number).map(ExprAstNode::Dport),
                text::keyword("sport").padded().ignore_then(port_number).map(ExprAstNode::Sport),
                text::keyword("port").padded().ignore_then(port_number).map(ExprAstNode::Port),
                text::keyword("l4proto").padded().ignore_then(protocol).map(ExprAstNode::Protocol),
                text::keyword("tcp").padded().to(ExprAstNode::Protocol(libc::IPPROTO_TCP)),
                text::keyword("udp").padded().to(ExprAstNode::Protocol(libc::IPPROTO_UDP)),
                text::keyword("state").padded().ignore_then(state).map(ExprAstNode::State),
                text::keyword("range").padded().ignore_then(range).map(ExprAstNode::Range),
            ));

            let negated = choice((
                simple.clone(),
                text::keyword("not").padded()
                    .ignore_then(simple)
                    .map(|expr| ExprAstNode::Negate(Box::new(expr)))
            ));

            let and = negated.clone().foldl(
                just("&&")
                    .padded()
                    .to(ExprAstNode::And as fn(_, _) -> _)
                    .then(negated)
                    .repeated(),
                |lhs, (op, rhs)| op(Box::new(lhs), Box::new(rhs)),
            );

            and.clone().foldl(
                just("||")
                    .padded()
                    .to(ExprAstNode::Or as fn(_, _) -> _)
                    .then(and)
                    .repeated(),
                |lhs, (op, rhs)| op(Box::new(lhs), Box::new(rhs)),
            )
        }).map(|ast| ast.into()).boxed();

        let string = none_of("\"").repeated()
            .collect::<String>()
            .delimited_by(just('"'), just('"'))
            .padded();

        let args = text::keyword("for").padded()
            .ignore_then(string.repeated().at_least(1).collect::<Vec<_>>().delimited_by(just('('), just(')')))
            .padded();

        let action = choice((
            rules.delimited_by(just('{'), just('}')).padded().map(Action::Chain),
            text::keyword("allow").padded().to(Action::Final(Verdict::Allow)),
            text::keyword("drop").padded().to(Action::Final(Verdict::Drop)),
            text::keyword("track").padded()
                .ignore_then(string)
                .then(args.or_not())
                .map(|(what, args)| Action::Track(what, args.unwrap_or_default()))
                .padded(),
        ));

        let rule = expr
            .or_not()
            .map(|expr| expr.unwrap_or(Expr::Always))
            .then(action)
            .map(|(expr, action)| Rule { expr, action });

        rule
            .repeated()
            .collect()
    })
}

/// Try to parse a filter program into a set of rules.
pub(crate) fn parse(input: &str) -> Result<Filter, Vec<Rich<'_, char>>> {
    parser().parse(input).into_result().map(|rules| Filter { rules })
}

/// Errors for `from_file`.
#[derive(Debug, thiserror::Error)]
pub(crate) enum FilterFromFileError {
    #[error("parse error: {0}")]
    ParseError(String), /* This hides away the lifetime of the underlying Rich error */
    #[error("IO error: {0}")]
    IoError(std::io::Error),
}
impl Into<std::io::Error> for FilterFromFileError {
    fn into(self) -> std::io::Error {
        match self {
            FilterFromFileError::ParseError(message)
                => std::io::Error::other(format!("Failed to parse filter: {message}")),
            FilterFromFileError::IoError(io) => io,
        }
    }
}

/// Try to parse a filter program into a set of rules, reading the input from a file.
pub(crate) fn from_file(path: impl AsRef<Path>) -> Result<Filter, FilterFromFileError> {
    let definition = std::fs::read_to_string(path).map_err(FilterFromFileError::IoError)?;
    parse(&definition).map_err(|e| FilterFromFileError::ParseError(format!("{e:?}")))
}
