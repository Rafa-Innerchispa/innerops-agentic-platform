
import os, subprocess, json, shutil

repo_ws = "/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform"
wt = "/home/rlopez/inneros/inneros_core/var/local_execution/worktrees/Rafa-Innerchispa__innerops-agentic-platform/antigravity__coordination-consolidation-p0"

results = {}

# Check which files have conflicts
st = subprocess.run(["git", "status", "-s"], cwd=repo_ws, capture_output=True, text=True)
results["status_before_resolve"] = st.stdout

# Copy all files from worktree to repo_ws to ensure 100% canonical resolution
for root, dirs, files in os.walk(wt):
    if ".git" in root:
        continue
    rel_dir = os.path.relpath(root, wt)
    target_dir = os.path.join(repo_ws, rel_dir)
    os.makedirs(target_dir, exist_ok=True)
    for f in files:
        src_f = os.path.join(root, f)
        dst_f = os.path.join(target_dir, f)
        shutil.copy2(src_f, dst_f)

# Add all files and complete merge commit
subprocess.run(["git", "add", "-A"], cwd=repo_ws, capture_output=True, text=True)

merge_commit = subprocess.run(["git", "commit", "-m", "Merge branch 'antigravity/coordination-consolidation-p0' into main - resolve P0 coordination consolidation"], cwd=repo_ws, capture_output=True, text=True)
results["merge_commit_stdout"] = merge_commit.stdout
results["merge_commit_stderr"] = merge_commit.stderr

main_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_ws, capture_output=True, text=True).stdout.strip()
results["main_head_sha_40"] = main_head

# Push to origin main
push_origin = subprocess.run(["git", "push", "origin", "main"], cwd=repo_ws, capture_output=True, text=True)
results["push_origin_stdout"] = push_origin.stdout
results["push_origin_stderr"] = push_origin.stderr

# Run tests in repo_ws to double check
test_res = subprocess.run(["pytest", "platform/tests/test_coordination_consolidation.py", "-v"], cwd=repo_ws, capture_output=True, text=True)
results["test_stdout"] = test_res.stdout

print("=== RESOLVE & PUSH RESULTS ===")
print(json.dumps(results, indent=2))
