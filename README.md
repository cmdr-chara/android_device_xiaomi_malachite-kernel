# Malachite transitional kernel artifacts

This owned repository is consumed at `device/xiaomi/malachite-kernel` by the malachite device tree. `BoardConfig.mk` currently forces the prebuilt path: `Image.lz4`, the DTB directory, three module directories and four load lists.

The initial source baseline is `9668297071a1d920b8aa6765e148840763c74d50` on `lineage-23.2`. That commit describes a selective migration to source-built modules with ACK 6.1.166. It is a hybrid compatibility baseline, not evidence that the current Xiaomi/MediaTek source kernel reproduces every artifact.

## Read-only validation

Python 3.10 or newer is sufficient:

```sh
python3 -m unittest discover -s tests -p 'test_prebuilt_inspector.py' -v
python3 tools/inspect_prebuilts.py > prebuilt-evidence.json
```

The inspector records SHA-256 hashes and sizes, recognizes the LZ4/DTB container headers, checks ELF64 little-endian AArch64 relocatable module headers, reads `.modinfo`, and checks each load-list name against its module directory. It does not decompress or validate the complete kernel image, load a module, inspect a phone, or change any artifact.

Duplicate load-list entries are reported and preserved pending load-order/runtime evidence. Different vermagic strings are reported, not treated as sufficient proof of either compatibility or incompatibility. Matching strings are not a substitute for symbol CRC/KMI and configuration checks. `release_status` remains `GAP` even when structural checks pass.

## Source-kernel migration gate

Build the pinned source workspace from [cmdr-chara/kernel_manifest-6.1](https://github.com/cmdr-chara/kernel_manifest-6.1), retaining its KMI checks. Compare the resulting kernel configuration, Image, DTB, module membership, vermagic, exported symbols/CRCs, signing, module load order and Android image packaging against this inventory before proposing replacements. Do not flatten an arbitrary dist directory over this repository or remove unmatched modules merely to satisfy a static checker.

`dtbo.img` is present for historical inventory only. The device tree deliberately stopped packaging DTBO after a reported cross-firmware hard-brick hazard. This validator does not re-enable it. Any future change requires exact device/region/firmware evidence and separate authorization; never downgrade or cross-flash low-level firmware to match a prebuilt.

No validation here authorizes flashing, rebooting, changing slots, formatting, or writing bootloader, GPT, NVRAM/NVDATA, calibration, seccfg or eFuse-sensitive storage. Android and physical-device build/boot/recovery checks remain separate gates.
