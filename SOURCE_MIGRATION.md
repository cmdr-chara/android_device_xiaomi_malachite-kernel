# Source-to-prebuilt module coverage gate

The current Android product consumes the four `modules.load.*` lists here. A
successful source-kernel build is not sufficient to replace those inputs.
`tools/compare_module_coverage.py` compares reported `.ko` basenames with all four
lists, preserves duplicates, and records the input revisions and SHA-256 hashes.
It never loads modules, edits a list, copies binary artifacts, or accesses a phone.

## Run the check

Obtain `generated-files.txt` from a reviewed kernel build's evidence archive.
Verify that archive's digest and its expanded manifest before trusting the input.
Use the prebuilt checkout whose exact commit you are recording:

```sh
python3 tools/compare_module_coverage.py \
  --generated-files /path/to/reviewed-build/generated-files.txt \
  --load-root . \
  --build-commit "$MANIFEST_COMMIT" \
  --prebuilt-commit "$PREBUILT_COMMIT" \
  --output new-coverage-report.json
```

`--build-commit` identifies the manifest/workflow revision, not just the kernel
repository. Keep its expanded 22-project manifest alongside the report. The tool
does not independently establish that a supplied revision or inventory is genuine.
Exit 0 means every required basename is reported, 1 means missing names, and 2
means invalid input/output. All reports retain `release_status=GAP`: staging and
unstripped paths are not a collected distribution, and equal names prove neither
ABI compatibility nor binary identity. Existing output reports are not overwritten.

## Actual comparison: successful KMI candidate

Inspected build: [33995588360](https://github.com/cmdr-chara/kernel_manifest-6.1/actions/runs/33995588360),
manifest commit `b48599ccd2758a15809347c321f98f5286b63574`, kernel candidate
`fc1616578c449fc0bf4a6a061046e2992347f3c6`. Its build log completed 503 actions.
Evidence ZIP SHA-256:
`85e586610de24ad607817bf26d8dce12121dea2bc2230dc0f9d2d7912a51b26d`.
`generated-files.txt` SHA-256:
`13c0bd72ec42257eaadbcd2a13894fe8cd5dfeaa7e28a9a7d3eb0a6ab73930aa`.
Prebuilt baseline: `9668297071a1d920b8aa6765e148840763c74d50`.

The inventory reports 817 distinct module basenames; the four load lists require
478 distinct names. **15 required names are absent** from that inventory:

| Consumed list | Absent basenames |
| --- | --- |
| system | None |
| recovery | bootprof.ko, mi_memory.ko |
| vendor | cpumaxfreq.ko, fpsgo.ko, frs.ko, lb.ko, mi_sw_sync.ko, migt.ko, mtk_fpsgo.ko, mtk_mbraink.ko, perf_helper.ko, xiaomi_wifi_gpio.ko |
| vendor_ramdisk | bootprof.ko, cpq.ko, mi_async_reclaim.ko, mi_memory.ko, mi_rmap_efficiency.ko, perf_helper.ko |

This is a coverage FAIL for direct replacement, not proof that every missing
module is required by every SKU or that the source is irreparable. Do not remove
entries to turn the report green.

## Resolve causes, not just names

The full Linux 6.1 config captured in [run 33998173925](https://github.com/cmdr-chara/kernel_manifest-6.1/actions/runs/33998173925)
has `CONFIG_MTPROF`, `CONFIG_MTK_MBRAINK` and `CONFIG_MTK_FPSGO_V3` unset.
The device-module tree has build rules for bootprof, mbraink and FPSGO/FRS;
the vendor-module tree also declares the `fpsgo_cus` target. These are explicit
configuration/build-graph questions, not sufficient grounds to enable them.

The malachite overlay requests `CONFIG_MI_WIFI_GPIO=m`, but that symbol is absent
from the generated config, and no matching definition was found in the selected
source export. A complete checkout/Kconfig traversal is required to distinguish
missing implementation from stale configuration. The prebuilt remains intact.

For each absent component trace Kconfig, Kleaf targets, source availability,
possible built-in/renamed replacements, exported symbols and actual consumers.
Then compare final distribution membership, module CRCs, signing, load order and
Image/DTB provenance. The prebuilt includes multiple historical vermagic strings;
that alone is neither proof of compatibility nor proof of failure.

## Verification state

PASS: 16 offline guard tests, including malformed input, duplicate paths,
traversal, symlink/oversize input rejection, deterministic hashes and non-overwrite
behavior. The actual retained build inventory produces the above coverage FAIL.
GAP: resolved per-module compatibility, complete source distribution, two clean
reproducibility builds, Android image packaging, AVB, VINTF, SELinux and separately
authorized boot/hardware tests. DTBO remains excluded from deployment.
