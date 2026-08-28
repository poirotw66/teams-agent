#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_dir="${project_root}/appPackage"
output_dir="${package_dir}/dist"
output_file="${output_dir}/teams-ai-agent.zip"

for required_file in manifest.json color.png outline.png; do
  if [[ ! -f "${package_dir}/${required_file}" ]]; then
    echo "Missing required app package file: ${package_dir}/${required_file}" >&2
    exit 1
  fi
done

mkdir -p "${output_dir}"
rm -f "${output_file}"

(
  cd "${package_dir}"
  zip -q "${output_file}" manifest.json color.png outline.png
)

echo "Created ${output_file}"
unzip -l "${output_file}"

