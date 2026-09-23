"""Installing a DomainPack, and what "remove the plugin" means (EXT-001, DOM-SP-001, §24.2).

    T-EXT-001     新增 ToyDomain 時 core package 無 source modification；plugin registration
                  即運作。
    T-DOM-SP-001  Rs trend validator 只存在 Silicon Photonics DomainPack，移除 plugin 後 core
                  仍可啟動。

THE SECOND CLAUSE IS WHAT MAKES THIS A REGISTRY AND NOT AN IMPORT. "Core still starts with the
plugin removed" is only checkable if installing a pack is an *act* rather than a side effect of
importing a module. A pack installed by import-time registration into a module-global would make
"not installed" unreachable without uninstalling Python, and the test would degrade into asserting
that an import succeeded.

So: `DomainPackRegistry.install(pack)` is the one entrance, `DomainRegistries()` with nothing
installed is a legal and useful state, and every consumer -- the planner, the tool registry, the
authority comparator -- resolves through the registries rather than importing a domain.

WHAT `install` DOES NOT DO. It does not import the pack, discover it, or scan a directory. The
caller constructs the pack and hands it over, which is what keeps the dependency edge pointing the
way §24.2 requires: the composition root knows about both, core knows about neither.
"""

from __future__ import annotations

from collections.abc import Iterator

from lab_brain.domains.base import DomainInstallError, DomainPack, DomainRegistries


class DomainPackRegistry:
    """Installed packs and the registries they wrote into.

    Holds the `DomainRegistries` rather than being handed one per call, so "what is installed" and
    "what was registered" cannot drift apart -- a pack recorded as installed whose registrations
    went somewhere else would be the worst of both.
    """

    def __init__(self, registries: DomainRegistries | None = None) -> None:
        self._registries = registries or DomainRegistries()
        self._packs: dict[str, DomainPack] = {}

    @property
    def registries(self) -> DomainRegistries:
        return self._registries

    def install(self, pack: DomainPack) -> DomainPack:
        """Run every `register_*` method, in a fixed order, into the shared registries.

        THE ORDER IS A DEPENDENCY ORDER, not a preference. Condition schemas first because a
        Capability may name a `conditions_schema_version` and a `run_*` tool must; backend validity
        before tools for the same reason; capabilities before tools because `ToolDescriptor`
        refuses a `run_*` tool with no capability and the registry is what makes that resolvable.
        Getting it wrong would surface as a pack that installs only if its own methods happen to
        be written in the right sequence.

        NOT TRANSACTIONAL, and that is stated rather than hidden: a pack that raises halfway leaves
        the registries holding its earlier registrations. Rolling back would need every registry to
        support removal, and a registry that supports removal is one where a capability can be
        silently withdrawn from under a plan. A failed install is a wiring error caught at start-up
        by a process that then does not start.
        """
        if not isinstance(pack, DomainPack):
            raise DomainInstallError(
                f"{pack!r} does not satisfy the DomainPack protocol (§24.3). A pack that is "
                "installed through a different shape is one core has to know about specially, "
                "which is the extension-boundary failure EXT-001 exists to detect"
            )
        if not pack.id or not pack.version:
            raise DomainInstallError("a DomainPack must declare a non-empty id and version")
        existing = self._packs.get(pack.id)
        if existing is not None:
            raise DomainInstallError(
                f"domain {pack.id} is already installed at version {existing.version}. Installing "
                "twice would re-run every registration, and the registries refuse a second, "
                "different registration under one identity -- so the failure would surface as "
                "whichever registry happened to be reached first"
            )

        pack.register_condition_schema(self._registries.conditions)
        pack.register_evidence_authority_policy(self._registries.authority)
        pack.register_backend_validity_schemas(self._registries.backend_validity)
        pack.register_validators(self._registries.validators)
        pack.register_metric_extractors(self._registries.extractors)
        pack.register_capabilities(self._registries.capabilities)
        pack.register_tools(self._registries.tools)
        pack.register_benchmarks(self._registries.benchmarks)

        self._packs[pack.id] = pack
        return pack

    def installed(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))

    def get(self, domain_id: str) -> DomainPack | None:
        return self._packs.get(domain_id)

    def require(self, domain_id: str) -> DomainPack:
        pack = self._packs.get(domain_id)
        if pack is None:
            raise DomainInstallError(
                f"domain {domain_id!r} is not installed. Installed: {self.installed() or 'nothing'}"
            )
        return pack

    def __iter__(self) -> Iterator[DomainPack]:
        return iter(self._packs[key] for key in sorted(self._packs))

    def __len__(self) -> int:
        return len(self._packs)


__all__ = ["DomainPackRegistry"]
