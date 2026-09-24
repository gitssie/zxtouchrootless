#!/bin/sh

# Rebuild the app and both package variants from one source revision.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/zxtouch-build.XXXXXX")
app="$root/layout/Applications/zxtouch.app"
postinst="$root/layout/DEBIAN/postinst"
roothide_postinst="$root/layout/DEBIAN/postinst-roothide"

cleanup() {
    if [ -d "$tmp/original.app" ]; then
        rm -rf "$app"
        cp -Rf "$tmp/original.app" "$app"
    fi
    if [ -f "$tmp/postinst" ]; then cp -f "$tmp/postinst" "$postinst"; fi
    if [ -f "$tmp/postinst-roothide" ]; then
        cp -f "$tmp/postinst-roothide" "$roothide_postinst"
    fi
    rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM

cp -Rf "$app" "$tmp/original.app"
cp -f "$postinst" "$tmp/postinst"
cp -f "$roothide_postinst" "$tmp/postinst-roothide"

if ! xcodebuild \
    -project "$root/zxtouch/zxtouch.xcodeproj" \
    -target zxtouch -sdk iphoneos -configuration Release \
    SYMROOT="$tmp/app-build" ONLY_ACTIVE_ARCH=NO ARCHS="arm64 arm64e" \
    CODE_SIGN_IDENTITY="" CODE_SIGNING_REQUIRED=NO \
    CODE_SIGNING_ALLOWED=NO AD_HOC_CODE_SIGNING_ALLOWED=YES \
    PRODUCT_BUNDLE_IDENTIFIER=com.zjx.zxtouch \
    >"$tmp/xcodebuild.log" 2>&1; then
    tail -n 60 "$tmp/xcodebuild.log" >&2
    exit 1
fi

built_app=$(find "$tmp/app-build" -type d -name zxtouch.app -print -quit)
[ -n "$built_app" ] || { echo "xcodebuild produced no app" >&2; exit 1; }
ldid -S"$root/zxtouch/app-entitlements.plist" "$built_app/zxtouch"
extension="$built_app/PlugIns/shortcutext.appex/shortcutext"
if [ -f "$extension" ]; then
    ldid -S"$root/zxtouch/shortcutext-entitlements.plist" "$extension"
fi
rm -rf "$app"
cp -Rf "$built_app" "$app"

version=$(awk -F': ' '$1 == "Version" { print $2; exit }' "$root/control")
[ -n "$version" ] || { echo "control has no Version" >&2; exit 1; }

make -C "$root" clean THEOS_PACKAGE_SCHEME=rootless
make -C "$root" package THEOS_PACKAGE_SCHEME=rootless FINALPACKAGE=1 -j2
cp -f "$root/packages/com.zjx.ioscontrol_${version}_iphoneos-arm64.deb" \
    "$root/packages/com.zjx.ioscontrol_${version}_rootless.deb"

cp -f "$roothide_postinst" "$postinst"
rm -f "$roothide_postinst"
make -C "$root" clean THEOS_PACKAGE_SCHEME=roothide
make -C "$root" package THEOS_PACKAGE_SCHEME=roothide FINALPACKAGE=1 \
    DISABLE_ROOTLESS_COMPAT_WARNING=1 -j2
cp -f "$root/packages/com.zjx.ioscontrol_${version}_iphoneos-arm64e.deb" \
    "$root/packages/com.zjx.ioscontrol_${version}_roothide.deb"

echo "rootless=$root/packages/com.zjx.ioscontrol_${version}_rootless.deb"
echo "roothide=$root/packages/com.zjx.ioscontrol_${version}_roothide.deb"
