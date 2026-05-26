# Architecture

Generally speaking, `ctfroute` manages "routing" or "the network stuff" for an A/D CTF.
Since this encompasses many features, both in terms of what we want to achieve and in
terms of networking subsystems we need to work with, there is a need to "break it down"
somehow. From the user-perspective, we are breaking the problem down into the concepts
described by our api spec. In our implementation, we want to break it down in a way that
makes the code maintainable and operable. While we are still in the early stages of
implementation, here are a few key ideas we had so far:

### Avoid parallelizing - but be prepared for it

As long as there no need for multi-threading or multiprocessing, we want to avoid the
complexity. Using `async` apis wherever possible should make us sufficiently fast. At
the same time, the code should be written in a way that allows us to migrate
"subsystems" to separate processes if their functionality is more time-critical than
that of others. For Example: The connectivity between routers shouldn't change during a
game. If we have to change something there, we will probably pause the game anyway.
Similarly, reconfiguring the connectivity of teams isn't as time critical as adjusting
gates or throttles. It is therefore not unlikely we will move the latter into (a)
separate process(es) to avoid them being held up by something in the other subsystems.

### Controllers

The first level of abstraction we introduced is (creatively) named controllers. A
controller should encapsulate some part of functionality that, well, can reasonably be
encapsulated and perhaps later be moved to a separate process. The job of a controller
is to consume the desired state, configure the system accordingly and then wait for
and react to changes in the desired state.

The tricky part is staking out the responsibilities for distinct controllers, **none of
this is gospel**, but here are a few properties we would like controllers to have:

- They should be able to operate independently of others
  - There shouldn't be any need for two controllers sharing a process
  - There also shouldn't be anything prohibiting two controllers sharing a process
- Controllers should manage resources like netlink sockets themselves
- IFF we find necessary communication between controllers, it should go through some
  kind of messaging or perhaps "extensions" of the state

Some (potential) controllers we already identified (none of this is set in stone):

- **WayFinder** ensures connectivity / routing between routers.

- **Concierge** manages connectivity for teams (vpn interfaces).

- **Cleaner** ensures that network traffic is properly anonymized.

- **PaceKeeper** ensures throttles in the desired state are enforced.

- **GateKeeper** ensures gates in the desired state are enforced.

- **Metrologist** exposes the internal state of ctfroute as metrics.

### Adapters

The purpose of adapters is to consume desired state from somewhere, we have an http
adapter that scrapes rest-endpoints that serve desired state as json. We also have a
kubernetes adapter that watches CRDs to derive desired state. As of writing only gates.

### Drivers

Drives make the implementation of functionality that controller provide swappable.
Potentially even for different entities of the same kind. E.g. the concierge might
connect different teams with different drivers.

### Who is responsible for copying?

Controllers and Adapters generally assume that they own the copy of data
that is passed to their methods (including **init**). The motivation is that
if we put different controllers into different processes, they necessarily
already receive a copy of the data that was exchanged over some ipc mechanism,
in that case we can avoid an unnecessary copy.

When running multiple controllers in one process it is thus the callers
responsibility to crate copies of objects before passing them to controllers or
adapters.

For drivers is the other way round, the drivers themselves are responsible
for creating copies of any state passed to them. The motivation here is that the
controllers are agnostic about what parts of state the drivers are aware of and
how.

## Feature ideas / TODOs:

- (How) do we prepare logging for parallelization?
