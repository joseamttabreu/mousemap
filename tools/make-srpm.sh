#!/bin/bash
# Gera o tarball e o SRPM. Uso: bash tools/make-srpm.sh [diretório de saída]
# Requer rpm-build. Também é usado pelo Copr (.copr/Makefile).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
outdir="$(realpath -m "${1:-$repo/build/rpm}")"
spec="$repo/packaging/mousemap.spec"
version="$(awk '/^Version:/ {print $2; exit}' "$spec")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Arquivos versionados + novos não ignorados (funciona mesmo antes do primeiro commit).
mkdir -p "$outdir" "$work/mousemap-$version"
(cd "$repo" && git ls-files --cached --others --exclude-standard -z) |
    (cd "$repo" && xargs -0 cp --parents -t "$work/mousemap-$version")
tar -C "$work" -czf "$work/mousemap-$version.tar.gz" "mousemap-$version"

rpmbuild -bs "$spec" \
    --define "_sourcedir $work" \
    --define "_srcrpmdir $outdir"
ls "$outdir"/mousemap-"$version"-*.src.rpm
