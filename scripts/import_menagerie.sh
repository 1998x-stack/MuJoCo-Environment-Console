#!/usr/bin/env bash
# Optional, on-demand, local copies of complete MJCF scenes and dependent meshes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v git >/dev/null || { echo 'git required'; exit 1; }
CACHE="$ROOT/data/menagerie-src"
if [[ ! -d "$CACHE/.git" ]]; then
  git clone --depth=1 --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie.git "$CACHE"
fi
cd "$CACHE"
git sparse-checkout set unitree_go2 unitree_g1 franka_emika_panda
git pull --ff-only
REV="$(git rev-parse --short HEAD)"
for item in unitree_go2 unitree_g1 franka_emika_panda; do
  dst="$ROOT/envs/menagerie_${item}"
  mkdir -p "$dst"
  cp -a "$CACHE/$item/." "$dst/"
  case "$item" in
    unitree_go2) title='Unitree Go2 · Scene' ;;
    unitree_g1) title='Unitree G1 · Scene' ;;
    franka_emika_panda) title='Franka Panda · Scene' ;;
  esac
  # Scene-only: MJCF gives physics and actuators but no well-designed RL objective.
  printf '{"kind":"mjcf","name":"%s","category":"Menagerie Scene","xml":"scene.xml","view_only":true,"frame_skip":5,"max_episode_steps":400}\n' "$title" > "$dst/manifest.json"
  echo "Imported $item ($REV)"
done
echo "Licensed assets remain in each model folder. Source revision: $REV"
echo 'Refresh the web catalog. Menagerie entries are simulation-only, not PPO/SAC tasks.'
