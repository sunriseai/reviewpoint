# Contributing to Reviewpoint

Keep the service domain-independent and the example singular. The host owns collection and execution; authenticated humans own decisions. Changes must preserve immutable input/profile bindings, project and host isolation, transactional history, explicit authority and fail-closed evaluation behavior.

Use the checks in [Development and operations](docs/development.md). Add tests for changed behavior rather than duplicating implementation. Maintain generated contracts and frontend assets. Document any new public field, identity assumption or operational limit.

The reference UI has two primary tasks: review work and manage risk guidelines. Keep developer details and less frequent administration behind secondary controls. Recommendations must remain separate from human choices, and actions must have adjacent feedback.

Use synthetic, generic data only. Do not add customer names, real evidence, credentials, local databases or private research. Test-only fixtures may exercise additional domains without turning into additional public demos. Run the release-content checker before proposing a public commit.

Contributions are governed by the repository's [MIT license](LICENSE).
