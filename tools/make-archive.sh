#!/bin/bash

# Run this in the directory that contain the areas' directories
# In other words, the areas.dir directory in config.toml

if [[ -z $1 ]]; then
  echo "Please specify YYYY-MM tag!"
  exit 1
fi
tag="$1"

for d in *; do
  [[ -d ${d} ]] || continue
  for f in "${d}"/*."${tag}.webp"; do
    if [[ -f "$f" ]]; then
      echo "${d} has archive"
    else
      echo -n "${d} has NO ARCHIVE! Generating..."
      err=0
      for ff in "${d}"/*."composited.png"; do
        targ="${ff%%.composited.png}.composited.${tag}.webp"
        if ! cwebp -quiet -preset picture -metadata all "$ff" -o "$targ"; then
          echo "ERROR"
          echo "  Failed creating .webp file for ${ff}"
          err=1
          continue
        fi
        exiftool -TagsFromFile "$ff" "$targ"
      done
      if [[ $err == 1 ]]; then
        echo "done."
      else
        echo "FAILED in ${d} !"
      fi
    fi
  done
done
