# Documentation

Formal documentation for the EU Border Risk Profiler. The structure
matches what is expected of a service handed over to an operations
team in an EU agency context: an ADR trail of the load-bearing
decisions, a Model Card and a Data Card to satisfy AI Act
documentation expectations, and a security posture statement.

| File | Purpose |
|------|---------|
| [`adr/README.md`](adr/README.md) | Index of Architecture Decision Records. |
| [`MODEL_CARD.md`](MODEL_CARD.md) | Predictive model description: scope, evaluation, limits, intended and out-of-scope uses. |
| [`DATA_CARD.md`](DATA_CARD.md) | Source dataset description: provenance, lag, biases, quality notes. |
| [`SECURITY.md`](SECURITY.md) | Threat model (STRIDE) and security controls. |

Operational guides (deployment, operations, Dokploy) live at the
repository root:

- [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md)
- [`../DOKPLOY_GUIDE.md`](../DOKPLOY_GUIDE.md)
- [`../OPERATIONS_GUIDE.md`](../OPERATIONS_GUIDE.md)
