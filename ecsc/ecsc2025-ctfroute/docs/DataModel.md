# ctfroute Data Model

# Routers, Teams, Throttles, Gates


# The meta field

All main entities in the system are equipped with a meta field. Its purpose is to 
easily transport and store small amounts of metadata for software integrating with 
ctfroute and parts of ctfoute itself. 

- ctfroute MUST handle absense of meta fields gracefully 
  - degraded functionality might be acceptable  
- Meta may not converge globally
- Controllers can issue updates of local labels
- Reserved namespace `ctfroute/.*`
- Similar to kubernetes annotations
- No "deletion", only set / overwrite
 
