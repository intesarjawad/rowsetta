#!/bin/sh
set -eu
file=${1:?usage: check_demo_gif.sh GIF}
bytes=$(wc -c < "$file" | tr -d ' ')
width=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$file")
duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$file")
awk -v bytes="$bytes" -v width="$width" -v duration="$duration" 'BEGIN {
  if (bytes >= 8000000 || width != 960 || duration < 9 || duration > 11) {
    printf "GIF failed: %d bytes, %d px, %.2f seconds\n", bytes, width, duration > "/dev/stderr";
    exit 1;
  }
  printf "GIF passed: %d bytes, %d px, %.2f seconds\n", bytes, width, duration;
}'
