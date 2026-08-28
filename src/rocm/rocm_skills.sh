#!/bin/bash
# Instalación y registro de skills de ROCm para agentes

# Directorio de skills
dir="/home/rlopez/data/rocm10-canary/skills"
mkdir -p "$dir"

# Instalar skills de diagnóstico
pip install rocm-cli-tools

# Registrar skills
skill_list=(
  "rocm-diagnose"
  "rocm-status"
  "rocm-profile"
)

for skill in "${skill_list[@]}"; do
  echo "{" > "$dir/$skill.json"
  echo "  \"name\": \"$skill\"," >> "$dir/$skill.json"
  echo "  \"description\": \"Skill de diagnóstico ROCm\"," >> "$dir/$skill.json"
  echo "  \"command\": \"rocm-cli $skill\"" >> "$dir/$skill.json"
  echo "}" >> "$dir/$skill.json"
done

# Documentar skills activas
echo "Skills registradas:" > "$dir/skills_active.txt"
for skill in "$dir"/*.json; do
  echo "$(basename "$skill")" >> "$dir/skills_active.txt"
done
