#!/usr/bin/env bash
# Rebuild std and the ordinary Cargo binary with one consistent thread ABI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
TOOLCHAIN=nightly-2026-09-25
SDK_VERSION=4.0.15
OUT="$ROOT/target/browser-threads"
export RUSTUP_TOOLCHAIN="$TOOLCHAIN"
export CARGO_TARGET_DIR="$OUT/cargo"
export EMCC_CFLAGS=-pthread
export RUSTFLAGS='-C target-feature=+atomics,+bulk-memory,+mutable-globals -C panic=abort -C link-arg=-pthread -C link-arg=-sPROXY_TO_PTHREAD=1 -C link-arg=-sPTHREAD_POOL_SIZE=4 -C link-arg=-sPTHREAD_POOL_SIZE_STRICT=2 -C link-arg=-sALLOW_BLOCKING_ON_MAIN_THREAD=0 -C link-arg=-sEXIT_RUNTIME=1 -C link-arg=-sINITIAL_MEMORY=67108864 -C link-arg=-sALLOW_MEMORY_GROWTH=0 -C link-arg=-sSTACK_SIZE=2097152 -C link-arg=-sDEFAULT_PTHREAD_STACK_SIZE=2097152 -C link-arg=-sASSERTIONS=2 -C link-arg=-sENVIRONMENT=web,worker'
emcc --version | head -n 1 | grep -F "$SDK_VERSION" >/dev/null
# This dedicated probe directory is disposable; never package stale sidecars.
rm -rf "$OUT/site" "$CARGO_TARGET_DIR" "$OUT/toolchain"
mkdir -p "$OUT/site"
export BROWSER_STD_SYSROOT="$(rustup run "$TOOLCHAIN" rustc --print sysroot)"
python3 tests/browser-threads/prepare-std.py --self-test
case "${BROWSER_STD_TLS_FIX:-0}" in
  0) printf '%s\n' '{"mode":"upstream-unmodified"}' > "$OUT/site/std-patch.json" ;;
  1)
    python3 tests/browser-threads/prepare-std.py --source "$BROWSER_STD_SYSROOT" --output "$OUT"
    export BROWSER_STD_SYSROOT="$OUT/toolchain"
    ;;
  *) echo 'BROWSER_STD_TLS_FIX must be 0 or 1' >&2; exit 1 ;;
esac
export RUSTC="$BROWSER_STD_SYSROOT/bin/rustc"
export CARGO_BUILD_RUSTC="$RUSTC"
test "$("$RUSTC" --print sysroot)" = "$BROWSER_STD_SYSROOT"
# The pinned compiler and opt-in patch stay confined to this probe.
"$BROWSER_STD_SYSROOT/bin/cargo" build --locked --release -p nxrs-browser-threads \
  --target wasm32-unknown-emscripten -Zbuild-std=std,panic_abort \
  --message-format=json-render-diagnostics | tee "$OUT/cargo-messages.jsonl"
python3 - "$OUT/site" <<'PY'
import hashlib, json, os, pathlib, shutil, subprocess, sys
site = pathlib.Path(sys.argv[1])
messages = [json.loads(line) for line in (site.parent / 'cargo-messages.jsonl').read_text().splitlines()]
std = [m for m in messages if m.get('reason') == 'compiler-artifact'
       and m['target']['name'] == 'std' and 'rlib' in m['target']['crate_types']]
assert len(std) == 1, 'expected exactly one std artifact'
actual = pathlib.Path(std[0]['target']['src_path']).resolve()
expected = pathlib.Path(os.environ['BROWSER_STD_SYSROOT']) / 'lib/rustlib/src/rust/library/std/src/lib.rs'
proof = dict(std_source=str(actual), expected_source=str(expected.resolve()),
             rustc=os.environ['RUSTC'], selected_source_matches=actual == expected.resolve())
(site / 'std-source.json').write_text(json.dumps(proof, indent=2) + '\n')
assert proof['selected_source_matches'], 'Cargo used the wrong std source'
release = pathlib.Path(os.environ['CARGO_TARGET_DIR']) / 'wasm32-unknown-emscripten/release'
# Cargo may copy/rename final outputs while retaining the emitted pair under
# build/.../out. Select a complete pair; identical Cargo copies are allowed.
wasms = list(release.rglob('*.wasm'))
pairs = [p for p in wasms if p.with_suffix('.js').is_file()]
assert pairs, f'no complete JS/WASM pair found beside {wasms}'
digests = {(hashlib.sha256(p.read_bytes()).hexdigest(),
            hashlib.sha256(p.with_suffix('.js').read_bytes()).hexdigest())
           for p in pairs}
assert len(digests) == 1, f'ambiguous emitted programs: {pairs}'
wasm = pairs[0]
js = wasm.with_suffix('.js')
for path in [js, wasm, *js.parent.glob('*.worker.js')]:
    shutil.copy2(path, site / path.name)
html = pathlib.Path('tests/browser-threads/index.html').read_text()
assert html.count('__NXRS_SCRIPT__') == 1
(site / 'index.html').write_text(html.replace('__NXRS_SCRIPT__', js.name))
def output(*args):
    return subprocess.check_output(args, text=True).strip()
manifest = {
    'source_sha': output('git', 'rev-parse', 'HEAD'),
    'rust': output(os.environ['RUSTC'], '--version', '--verbose'),
    'emscripten': output('emcc', '--version'),
    'rustflags': os.environ['RUSTFLAGS'],
    'emcc_cflags': os.environ['EMCC_CFLAGS'],
    'std_patch': json.loads((site / 'std-patch.json').read_text()),
    'std_source': proof,
    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(site.iterdir()) if p.is_file() and p.name != 'manifest.json'},
    'probe_sha256': hashlib.sha256(pathlib.Path('tests/browser-threads/src/main.rs').read_bytes()).hexdigest(),
}
(site / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
PY
