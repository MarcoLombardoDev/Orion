#!/bin/sh
# Start Orion, after checking that the executable is the one this archive was
# built with.
#
# The archive ships a `.sha256` beside the executable. This script recomputes
# that digest and compares. What that catches is a truncated download, a
# half-finished unpack, a disk that has started rotting — damage, in other
# words, which is the failure that actually happens to people.
#
# What it does NOT catch is tampering. The checksum travels inside the same
# archive as the file it describes, so anyone able to alter the executable
# could alter the checksum in the same breath. The check worth doing against
# that is on the archive itself, using the `.sha256` published as a separate
# release asset — it reaches you by a different path, which is the whole
# point. The README says how.
#
# Portable /bin/sh on purpose: it runs on the Linux build and, renamed
# start.command so Finder will double-click it, on the macOS one.

set -eu

APP="Orion"

# The directory this script lives in, not the one it was invoked from: a
# double-click from a file manager starts somewhere else entirely.
#
# Stripped with parameter expansion rather than dirname, and everything below
# reads the same way: apart from the hashing tool itself, this script calls
# nothing external. A launcher is the last thing that should fail because the
# environment it inherited was unusual.
case "$0" in
    */*) dir=${0%/*} ;;
    *)   dir=. ;;
esac
here=$(CDPATH= cd -- "$dir" && pwd)

if [ -d "$here/$APP.app" ]; then
    exe="$here/$APP.app/Contents/MacOS/$APP"   # macOS: inside the bundle
else
    exe="$here/$APP"
fi

sums="$here/$APP.sha256"

if [ ! -x "$exe" ]; then
    if [ -f "$exe" ]; then
        chmod +x "$exe" 2>/dev/null || true
    fi
fi

if [ ! -f "$exe" ]; then
    echo "$APP: no executable at $exe" >&2
    echo "The archive did not unpack completely. Unpack it again." >&2
    exit 1
fi

digest_of() {
    # Three tools, because no single one is on every system: sha256sum is
    # coreutils (Linux), shasum ships with macOS, openssl is usually on both.
    # The first two print "<hex>  <path>", so the hex is everything up to the
    # first space; openssl prints "SHA2-256(path)= <hex>", so it is everything
    # after the last one.
    if command -v sha256sum > /dev/null 2>&1; then
        line=$(sha256sum "$1") && printf '%s\n' "${line%% *}"
    elif command -v shasum > /dev/null 2>&1; then
        line=$(shasum -a 256 "$1") && printf '%s\n' "${line%% *}"
    elif command -v openssl > /dev/null 2>&1; then
        line=$(openssl dgst -sha256 "$1") && printf '%s\n' "${line##* }"
    else
        return 1
    fi
}

# An escape hatch that is deliberately explicit. Somebody who has patched the
# executable on purpose should be able to run it; somebody who has not should
# never see this path taken silently.
if [ "${ORION_SKIP_VERIFY:-}" = "1" ]; then
    echo "$APP: checksum verification skipped (ORION_SKIP_VERIFY=1)" >&2
elif [ ! -f "$sums" ]; then
    echo "$APP: $APP.sha256 is missing, starting without checking" >&2
elif ! actual=$(digest_of "$exe"); then
    echo "$APP: no sha256 tool found, starting without checking" >&2
else
    # The file is in the format sha256sum -c reads: "<hex>  <path>".
    # `read` reports EOF on a file with no trailing newline but has assigned
    # by then, so its status is ignored and the emptiness checked instead.
    expected=""
    read -r expected _ < "$sums" || :
    if [ -z "$expected" ]; then
        echo "$APP: $APP.sha256 is empty, starting without checking" >&2
    elif [ "$actual" != "$expected" ]; then
        echo "$APP: the executable does not match $APP.sha256." >&2
        echo "  expected $expected" >&2
        echo "  found    $actual" >&2
        echo "" >&2
        echo "Unpack the archive again from a fresh download. If it still" >&2
        echo "does not match, check the archive's own .sha256 from the" >&2
        echo "release page before running anything out of it." >&2
        exit 1
    fi
fi

exec "$exe" "$@"
