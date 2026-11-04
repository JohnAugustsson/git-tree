#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install git-tree for the current user.

Usage: ./install.sh [options]

Options:
  --prefix PATH   Installation prefix (default: ~/.local)
  --link          Link this checkout instead of copying it (development)
  -h, --help      Show this help

Installs PREFIX/bin/git-tree, which git runs as `git tree`, and its manual
page, which `git tree --help` opens.
EOF
}

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
prefix=${GIT_TREE_PREFIX:-$HOME/.local}
link_mode=0

while (($#)); do
  case $1 in
    --prefix)
      (($# >= 2)) || { printf 'install.sh: --prefix requires a path\n' >&2; exit 2; }
      prefix=$2
      shift 2
      ;;
    --prefix=*)
      prefix=${1#*=}
      shift
      ;;
    --link)
      link_mode=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'install.sh: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $prefix != /* ]]; then
  printf 'install.sh: --prefix must be an absolute path\n' >&2
  exit 2
fi

for required in bin/git-tree src/git_tree docs/git-tree.1; do
  if [[ ! -e $repo_root/$required ]]; then
    printf 'install.sh: checkout is incomplete; missing %s\n' "$required" >&2
    exit 1
  fi
done

data_root=$prefix/share/git-tree
bin_dir=$prefix/bin
man_dir=$prefix/share/man/man1

ensure_link() {
  local source=$1
  local target=$2
  mkdir -p -- "$(dirname -- "$target")"
  if [[ -L $target ]]; then
    [[ $(readlink -- "$target") == "$source" ]] || ln -sfn -- "$source" "$target"
    return 0
  fi
  if [[ -e $target ]]; then
    printf 'install.sh: refusing to replace existing path: %s\n' "$target" >&2
    return 1
  fi
  ln -s -- "$source" "$target"
}

mkdir -p -- "$prefix/share"
if ((link_mode)); then
  if [[ -e $data_root && ! -L $data_root ]]; then
    printf 'install.sh: cannot use --link over copied install: %s\n' "$data_root" >&2
    exit 1
  fi
  ensure_link "$repo_root" "$data_root"
else
  if [[ -L $data_root ]]; then
    printf 'install.sh: cannot copy over linked install: %s\n' "$data_root" >&2
    exit 1
  fi
  # Replace rather than merge, so files a newer version dropped don't linger.
  rm -rf -- "${data_root:?}/bin" "${data_root:?}/src" "${data_root:?}/docs"
  mkdir -p -- "$data_root/docs"
  cp -a -- "$repo_root/bin" "$repo_root/src" "$data_root/"
  cp -a -- "$repo_root/docs/git-tree.1" "$data_root/docs/"
  cp -a -- "$repo_root/README.md" "$repo_root/LICENSE" "$data_root/"
fi

ensure_link "$data_root/bin/git-tree" "$bin_dir/git-tree"
ensure_link "$data_root/docs/git-tree.1" "$man_dir/git-tree.1"

printf 'Installed git-tree in %s\n' "$data_root"
if [[ :$PATH: != *:$bin_dir:* ]]; then
  printf 'Add %s to PATH so git can run "git tree".\n' "$bin_dir"
fi
