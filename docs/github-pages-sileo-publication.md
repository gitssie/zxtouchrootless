# ZXTouch GitHub Pages / Sileo publication

This fork follows ProjectX's local publication model: build and sign on the maintainer's Mac, generate and verify a static APT repository, then make an ordinary non-force push to `gh-pages` from an isolated temporary Git checkout. GitHub Pages serves files; it does not build the tweak.

## Setup

1. Set `origin` to `git@github.com:gitssie/zxtouchrootless.git`.
2. Keep `main` clean and push the exact source commit to `origin/main`.
3. In GitHub **Settings → Pages**, choose **Deploy from a branch → gh-pages → /(root)**.
4. Add `https://gitssie.github.io/zxtouchrootless` to Sileo without a trailing slash.

## Publish

```sh
scripts/publish_github_pages.sh --dry-run publish
scripts/publish_github_pages.sh publish
```

The publisher builds the current app and both package variants, checks package identifiers, versions, architectures, roothide/rootless install scripts, index compression, hashes, and `Release` entries. It replaces the public snapshot with both `.deb` files and a site pointing to this fork. `main` stays on `main`; build substitutions are restored. Republishing byte-identical packages is a no-op.

Use `--skip-build` only when both current-version packages were just built by `scripts/build_packages.sh` from the same source. The publisher still checks their metadata and hashes.

The published `gh-pages` branch contains `.nojekyll`, `index.html`, `favicon.svg`, `depiction.json`, `Packages`, `Packages.gz`, `Packages.xz`, `Packages.zst`, `Release`, and both packages under `debs/`.
