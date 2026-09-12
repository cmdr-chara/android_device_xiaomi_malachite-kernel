# Prebuilt kernel agent instructions

## Artifact contracts

- This is the Android-consumed prebuilt artifact repository, not the source kernel. Preserve existing Image, DTB, module, and load-list bytes during read-only inspection/tooling changes.
- Do not remove duplicate or unmatched load entries simply to satisfy a checker. Preserve load order until producer/consumer and runtime evidence justify an intentional change.
- A matching filename, ELF header, or vermagic string is not proof of ABI/KMI, symbol CRC, signing, configuration, or firmware compatibility.
- Keep the documented DTBO deployment exclusion. Presence of `dtbo.img` is historical inventory, not permission to package or flash it.
- Any replacement proposal needs pinned source/build provenance and artifact-level comparison; never flatten an arbitrary distribution over the trusted baseline.

## Guidance and verification

Use [README.md](README.md) for inspector scope and [SOURCE_MIGRATION.md](SOURCE_MIGRATION.md) for migration evidence. Run the affected Python tests in `tests/`; the documented inspector is read-only and must not load modules or execute artifacts.

Separate source-contract checks from actual artifact inspection, populated build outputs, Android packaging, and hardware tests. Preserve honest GAP/failure results rather than treating structural success as release readiness.

Finish with the requested tooling/evidence checked and unchanged-payload claims verified against the base. Repository permission does not authorize flashing, rebooting, slot changes, wipes, or sensitive-partition access.
