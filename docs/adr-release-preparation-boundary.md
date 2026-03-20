# ADR: Cadis Release Preparation and Consumer Build Boundary

## Status

Accepted

## Context

Cadis is an open source administrative lookup component that may be embedded into downstream services requiring sealed, reproducible deployment inputs.

Cadis runtime behavior depends on both:

- the Cadis package version
- the installed dataset versions

As a result, reproducible deployment requires more than pinning application code. It also requires:

- pinning dataset versions
- defining an approved dataset release set
- materializing datasets in a controlled way before deployment

Cadis now provides:

- pinned package versioning
- pinned dataset version support
- an approved production manifest in `releases/stable.json`
- `scripts/prepare_release.sh` for deterministic dataset preparation
- checksum-verified dataset materialization into a prepared cache artifact

Before these materials existed, downstream consumers could reasonably model dataset preparation as their own pre-build concern. With these materials in place, the ownership boundary becomes clearer.

## Decision

We define the deployment boundary as:

`Cadis release preparation -> consumer image build -> runtime`

### Cadis owns release preparation

Cadis is responsible for:

- publishing the approved production manifest
- pinning Cadis version and dataset versions
- preparing the dataset cache artifact from the approved manifest
- verifying artifact integrity during preparation

This step may happen before final image assembly, but it is conceptually part of Cadis release preparation rather than consumer-specific build logic.

### The downstream consumer owns image composition

A downstream service that embeds Cadis is responsible for:

- consuming the prepared Cadis artifact as a locked input
- deciding which approved Cadis artifact is admitted into a given image or deployment
- applying any deployment-specific country inclusion policy
- recording that decision in its own deployment metadata if needed
- assembling the final runtime image or package

The downstream consumer should not independently resolve dataset versions and should not fetch Cadis datasets during final image assembly or runtime.

### Runtime remains sealed

At runtime:

- the service reads only the sealed Cadis dataset root shipped with the image or mounted as an approved artifact
- runtime must not fetch or mutate Cadis datasets

## Rationale

This decision preserves two important properties:

1. Reproducibility  
   Cadis datasets are pinned, prepared, and verified from an approved manifest.

2. Build boundary clarity  
   The downstream consumer assembles images from already-materialized inputs instead of performing upstream dataset acquisition itself.

This avoids duplicate responsibility:

- Cadis owns dataset release preparation
- the downstream consumer owns image composition and deployment policy

It also avoids requiring each adopter to invent a parallel preparation model when Cadis already provides the correct upstream deployment primitive.

## Consequences

### Positive

- clear ownership boundary between Cadis and downstream consumers
- deterministic production rollout based on pinned manifests
- no runtime dataset fetch
- no duplicate dataset preparation logic in downstream systems
- easier explanation to build and release teams

### Negative

- there is still a step before final image assembly where Cadis artifacts must be prepared
- downstream consumers still need their own policy for:
  - which ISO set to ship in a given deployment
  - which prepared artifact to admit
  - how to express that in their own deployment metadata

### Neutral

- a step before final image assembly may still exist in practice
- however, that step is better understood as Cadis artifact preparation, not as a Cadis feature gap

## Non-Goals

This ADR does not define:

- any downstream service’s deployment metadata schema
- image-specific country inclusion policy
- internal artifact registry or storage conventions
- release promotion workflow details beyond the Cadis/consumer boundary

## Operational Rule

Production deployment using Cadis should satisfy all of the following:

- pinned Cadis version
- pinned dataset versions
- approved Cadis release manifest
- prepared Cadis artifact generated from that manifest
- downstream build assembled only from that prepared artifact

## References

- [stable.json](/Users/isempty/Projects/my_cadis/cadis/releases/stable.json)
- [prepare_release.sh](/Users/isempty/Projects/my_cadis/cadis/scripts/prepare_release.sh)
- [deployment.md](/Users/isempty/Projects/my_cadis/cadis/docs/deployment.md)
- [cicd-examples.md](/Users/isempty/Projects/my_cadis/cadis/docs/cicd-examples.md)
