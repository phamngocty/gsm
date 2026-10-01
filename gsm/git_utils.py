import subprocess
import os
from pathlib import Path
from typing import Optional


def _run_git(args: list, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    return result


def _run_git_lines(args: list, cwd: Optional[str] = None) -> dict:
    r = _run_git(args, cwd)
    lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()] if r.stdout else []
    err_lines = [l.strip() for l in r.stderr.strip().splitlines() if l.strip()] if r.stderr else []
    return {"success": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
            "lines": lines, "error_lines": err_lines, "returncode": r.returncode}


def is_git_repo(path: str) -> bool:
    return (Path(path) / ".git").is_dir()


def clone_repo(url: str, target_dir: str) -> list[str]:
    lines: list[str] = []
    proc = subprocess.Popen(
        ["git", "clone", url, target_dir], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    if proc.stdout:
        for line in proc.stdout:
            line = line.strip()
            if line: lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Clone failed: {' | '.join(lines[-3:])}")
    return lines


def git_check_index_lock(project_path: str) -> dict:
    """Check if .git/index.lock exists."""
    lock_file = Path(project_path) / ".git" / "index.lock"
    is_locked = lock_file.is_file()
    return {"is_locked": is_locked, "lock_file": str(lock_file) if is_locked else ""}


def git_unlock(project_path: str) -> dict:
    """Remove .git/index.lock if present."""
    lock_file = Path(project_path) / ".git" / "index.lock"
    if lock_file.exists():
        try:
            lock_file.unlink()
            return {"success": True, "message": "Đã mở khóa repository (xóa .git/index.lock)"}
        except Exception as e:
            return {"success": False, "error": f"Không thể xóa index.lock: {str(e)}"}
    return {"success": True, "message": "Repository không bị khóa"}


def _auto_clean_stale_lock(project_path: str) -> bool:
    """If index.lock exists and no git process is running or it is stale (>5s), automatically remove it."""
    lock_file = Path(project_path) / ".git" / "index.lock"
    if not lock_file.exists():
        return False
    try:
        import time
        # If lock file is older than 5 seconds, it is almost certainly stale from a finished/crashed process
        age = time.time() - lock_file.stat().st_mtime
        if age > 5:
            lock_file.unlink(missing_ok=True)
            return True
        # Check if git.exe is currently running
        out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq git.exe", "/FO", "CSV"], text=True)
        if "git.exe" not in out:
            lock_file.unlink(missing_ok=True)
            return True
    except Exception:
        pass
    return False


def get_status(project_path: str) -> dict:
    result = {"branch": "unknown", "has_conflict": False, "files": [], "ahead": 0, "behind": 0, "is_locked": False}
    if not is_git_repo(project_path):
        return result

    # Check lock status (and auto-clean if stale)
    lock_info = git_check_index_lock(project_path)
    result["is_locked"] = lock_info["is_locked"]
    if result["is_locked"] and _auto_clean_stale_lock(project_path):
        result["is_locked"] = False

    r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path)
    result["branch"] = r.stdout.strip() if r.returncode == 0 else "HEAD (detached)"
    # Use core.quotepath=false so Unicode/diacritics filenames aren't octal escaped
    r = _run_git(["-c", "core.quotepath=false", "status", "--porcelain", "-uall"], cwd=project_path)
    if r.returncode == 0:
        for raw_line in r.stdout.splitlines():
            if not raw_line or len(raw_line) < 3:
                continue
            xy = raw_line[:2]
            filename = raw_line[3:].strip()
            # Strip outer quotes added by git for paths with spaces
            if filename.startswith('"') and filename.endswith('"'):
                filename = filename[1:-1]
            if " -> " in filename:
                filename = filename.split(" -> ")[-1].strip()
                if filename.startswith('"') and filename.endswith('"'):
                    filename = filename[1:-1]
            status = _parse_porcelain(xy)
            result["files"].append({"path": filename, "status": status})
            if status == "Conflict": result["has_conflict"] = True
    r = _run_git(["rev-list", "--count", "--left-right", "@{upstream}...HEAD"], cwd=project_path)
    if r.returncode == 0:
        parts = r.stdout.strip().split("\t")
        if len(parts) == 2:
            try: result["behind"], result["ahead"] = int(parts[0]), int(parts[1])
            except ValueError: pass
    return result


def _parse_porcelain(xy: str) -> str:
    if len(xy) < 2:
        return "Modified"
    x, y = xy[0], xy[1]

    # Merge conflicts in porcelain v1
    if xy in ["UU", "AA", "DD", "AU", "UD", "UA", "DU"]:
        return "Conflict"
    if xy == "??":
        return "Untracked"
    if xy == "!!":
        return "Ignored"

    # Index is staged (x is non-space)
    if x in ["M", "A", "D", "R", "C"]:
        if y != " ":
            return "Staged+Modified"
        return "Staged"

    # Index is clean, worktree has modifications (x is space)
    if x == " ":
        if y == "M":
            return "Modified"
        if y == "D":
            return "Deleted"
        if y == "A":
            return "Added"
        if y == "R":
            return "Renamed"
        return "Modified"

    return xy


def get_recent_commits(project_path: str, limit: int = 10) -> list[dict]:
    commits = []
    if not is_git_repo(project_path): return commits
    r = _run_git(["log", f"--max-count={limit}", "--format=%H|%s|%an|%ai", "--no-color"], cwd=project_path)
    if r.returncode != 0: return commits
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0][:8], "message": parts[1], "author": parts[2], "date": parts[3]})
    return commits


def open_in_fork(fork_path: str, project_path: str) -> None:
    subprocess.Popen(
        [fork_path, project_path], shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def setup_multi_push(project_path: str, github_url: str, gitea_url: str) -> list[str]:
    lines = []
    if not is_git_repo(project_path): raise RuntimeError("Not a git repository")
    r = _run_git(["remote", "get-url", "origin"], cwd=project_path)
    if r.returncode != 0:
        _run_git(["remote", "add", "origin", github_url], cwd=project_path)
        lines.append(f"Added remote origin -> {github_url}")
    else:
        _run_git(["remote", "set-url", "origin", github_url], cwd=project_path)
        lines.append(f"Updated remote origin -> {github_url}")
    r = _run_git(["remote", "get-url", "gitea"], cwd=project_path)
    if r.returncode != 0:
        _run_git(["remote", "add", "gitea", gitea_url], cwd=project_path)
        lines.append(f"Added remote gitea -> {gitea_url}")
    else:
        _run_git(["remote", "set-url", "gitea", gitea_url], cwd=project_path)
        lines.append(f"Updated remote gitea -> {gitea_url}")
    r = _run_git(["remote", "get-url", "--push", "origin"], cwd=project_path)
    if r.returncode == 0:
        for u in [u.strip() for u in r.stdout.strip().splitlines() if u.strip()]:
            if u != github_url: _run_git(["remote", "set-url", "--delete", "--push", "origin", u], cwd=project_path)
    _run_git(["remote", "set-url", "--add", "--push", "origin", gitea_url], cwd=project_path)
    lines.append("Multi-push configured")
    r = _run_git(["remote", "-v"], cwd=project_path)
    lines.extend([l.strip() for l in r.stdout.strip().splitlines() if l.strip()])
    return lines


def has_multi_push(project_path: str) -> bool:
    r = _run_git(["remote", "get-url", "--push", "origin"], cwd=project_path)
    if r.returncode != 0: return False
    return len([u.strip() for u in r.stdout.strip().splitlines() if u.strip()]) > 1


def git_init(project_path: str) -> dict:
    """Initialize a git repo and create initial commit so repo is not empty."""
    result = _run_git_lines(["init"], cwd=project_path)
    if not result.get("success"):
        return result
    # Create .gitkeep so repo has at least one file
    gitkeep = os.path.join(project_path, ".gitkeep")
    try:
        with open(gitkeep, "w") as f:
            f.write("")
    except:
        pass
    _run_git_lines(["add", ".gitkeep"], cwd=project_path)
    commit_result = _run_git_lines(["commit", "-m", "Initial commit"], cwd=project_path)
    if commit_result.get("success"):
        result["stdout"] += "\n" + commit_result.get("stdout", "")
    return result


def git_stage_file(project_path: str, file_path: str) -> dict:
    _auto_clean_stale_lock(project_path)
    return _run_git_lines(["add", file_path], cwd=project_path)


def git_unstage_file(project_path: str, file_path: str) -> dict:
    _auto_clean_stale_lock(project_path)
    return _run_git_lines(["reset", "HEAD", "--", file_path], cwd=project_path)


def git_stage_all(project_path: str) -> dict:
    _auto_clean_stale_lock(project_path)
    return _run_git_lines(["add", "-A"], cwd=project_path)


def git_stage_all_progress(project_path: str, chunk_size: int = 5):
    """Stage all files with incremental progress generator for real-time percentage progress bar."""
    if not is_git_repo(project_path):
        yield {"success": False, "error": "Not a git repository", "percent": 0, "current": 0, "total": 0}
        return

    _auto_clean_stale_lock(project_path)
    lock = git_check_index_lock(project_path)
    if lock["is_locked"]:
        yield {
            "success": False,
            "error": "Repository đang bị khóa bởi .git/index.lock. Vui lòng mở khóa để tiếp tục.",
            "is_locked": True,
            "percent": 0,
            "current": 0,
            "total": 0,
        }
        return

    # Query all modified/untracked files
    r = _run_git(["-c", "core.quotepath=false", "status", "--porcelain", "-uall"], cwd=project_path)
    if r.returncode != 0:
        yield {"success": False, "error": r.stderr.strip() or "Git status failed", "percent": 0, "current": 0, "total": 0}
        return

    files_to_add = []
    for raw_line in r.stdout.splitlines():
        if not raw_line or len(raw_line) < 3:
            continue
        xy = raw_line[:2]
        # Skip if already fully staged (clean in worktree)
        if xy in ["M ", "A ", "D ", "R ", "C "]:
            continue
        fn = raw_line[3:].strip()
        if fn.startswith('"') and fn.endswith('"'):
            fn = fn[1:-1]
        if " -> " in fn:
            fn = fn.split(" -> ")[-1].strip()
            if fn.startswith('"') and fn.endswith('"'):
                fn = fn[1:-1]
        files_to_add.append(fn)

    total = len(files_to_add)
    if total == 0:
        yield {
            "success": True,
            "done": True,
            "percent": 100,
            "current": 0,
            "total": 0,
            "message": "Tất cả file đã được stage hoặc không có thay đổi."
        }
        return

    # Yield initial 0% event
    yield {
        "success": True,
        "done": False,
        "percent": 0,
        "current": 0,
        "total": total,
        "file": files_to_add[0]
    }

    if chunk_size is None or chunk_size <= 5:
        if total > 500:
            actual_chunk_size = 50
        elif total > 100:
            actual_chunk_size = 20
        elif total > 30:
            actual_chunk_size = 10
        else:
            actual_chunk_size = 5
    else:
        actual_chunk_size = chunk_size

    processed = 0
    errors = []
    for i in range(0, total, actual_chunk_size):
        chunk = files_to_add[i : i + actual_chunk_size]
        # Use git add -A -- chunk to support new, modified, and deleted files
        r_add = _run_git(["add", "-A", "--"] + chunk, cwd=project_path)
        if r_add.returncode != 0:
            # Fallback to single-file staging for each item in this chunk
            chunk_success_count = 0
            for single_file in chunk:
                r_single = _run_git(["add", "-A", "--", single_file], cwd=project_path)
                if r_single.returncode == 0:
                    chunk_success_count += 1
                else:
                    errors.append(f"{single_file}: {r_single.stderr.strip() or 'add failed'}")
                processed += 1
                pct = min(99, int((processed / total) * 100))
                yield {
                    "success": True,
                    "done": False,
                    "percent": pct,
                    "current": processed,
                    "total": total,
                    "file": single_file
                }
            if chunk_success_count == 0 and len(chunk) > 0 and len(errors) == total:
                # Every single file in the repo failed, e.g. locked index
                first_err = errors[0] if errors else "git add failed"
                yield {
                    "success": False,
                    "error": first_err,
                    "is_locked": "index.lock" in first_err,
                    "percent": int((processed / total) * 100),
                    "current": processed,
                    "total": total,
                    "file": chunk[0]
                }
                return
            continue

        processed += len(chunk)
        pct = min(99, int((processed / total) * 100))
        yield {
            "success": True,
            "done": False,
            "percent": pct,
            "current": processed,
            "total": total,
            "file": chunk[-1]
        }

    # Final completion event
    yield {
        "success": len(errors) < total,
        "done": True,
        "percent": 100,
        "current": total,
        "total": total,
        "file": "",
        "warnings": errors if errors else None
    }


def git_commit(project_path: str, message: str) -> dict:
    _auto_clean_stale_lock(project_path)
    return _run_git_lines(["commit", "-m", message], cwd=project_path)


def git_push(project_path: str, remote: str = "origin", branch: str = "", force: bool = False) -> dict:
    """Push to remote. Auto-retry with --set-upstream if no upstream configured."""
    args = ["push"]
    if force:
        args.append("--force")
    args.append(remote)
    if branch: args.append(branch)
    result = _run_git_lines(args, cwd=project_path)

    # If failed due to no upstream, auto-retry with --set-upstream
    if not result.get("success"):
        stderr = (result.get("stderr") or "").lower()
        if "no upstream" in stderr or "no upstream branch" in stderr:
            # Get current branch if not specified
            if not branch:
                r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path)
                if r.returncode == 0:
                    branch = r.stdout.strip()
            if branch and branch != "HEAD":
                retry_args = ["push", "--set-upstream", remote, branch]
                result = _run_git_lines(retry_args, cwd=project_path)
    return result


def git_pull(project_path: str, remote: str = "origin", branch: str = "") -> dict:
    _auto_clean_stale_lock(project_path)
    args = ["pull", remote]
    if branch: args.append(branch)
    return _run_git_lines(args, cwd=project_path)


def git_fetch(project_path: str, remote: str = "") -> dict:
    args = ["fetch"]
    if remote: args.append(remote)
    return _run_git_lines(args, cwd=project_path)


def git_push_tag(project_path: str, tag: str, remote: str = "origin") -> dict:
    """Push a specific tag to remote."""
    return _run_git_lines(["push", remote, tag], cwd=project_path)


def git_branch_list(project_path: str) -> list[dict]:
    result = []
    r = _run_git([
        "for-each-ref",
        "--format=%(refname:short)|%(HEAD)|%(objectname:short)|%(upstream:short)|%(upstream:track)|%(committerdate:relative)|%(subject)",
        "refs/heads", "refs/remotes"
    ], cwd=project_path)

    if r.returncode == 0 and r.stdout.strip():
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line: continue
            parts = line.split("|", 6)
            name = parts[0].strip()
            if not name or "->" in name or name == "origin": continue
            is_current = len(parts) > 1 and parts[1].strip() == "*"
            hash_val = parts[2].strip() if len(parts) > 2 else ""
            upstream = parts[3].strip() if len(parts) > 3 else ""
            track = parts[4].strip("[] ").strip() if len(parts) > 4 else ""
            date = parts[5].strip() if len(parts) > 5 else ""
            subject = parts[6].strip() if len(parts) > 6 else ""
            is_remote = name.startswith("origin/") or name.startswith("remotes/")
            result.append({
                "name": name,
                "current": is_current,
                "remote": is_remote,
                "hash": hash_val,
                "upstream": upstream,
                "track": track,
                "date": date,
                "subject": subject
            })
        if result: return result

    # Fallback to standard git branch --all
    r = _run_git(["branch", "--all"], cwd=project_path)
    if r.returncode != 0: return result
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        is_current = line.startswith("*")
        name = line.lstrip("* ").strip()
        if "->" in name: continue
        result.append({
            "name": name,
            "current": is_current,
            "remote": name.startswith("remotes/") or name.startswith("origin/"),
            "hash": "",
            "upstream": "",
            "track": "",
            "date": "",
            "subject": ""
        })
    return result


def git_branch_create(project_path: str, name: str, from_branch: str = "") -> dict:
    args = ["branch", name]
    if from_branch: args.append(from_branch)
    return _run_git_lines(args, cwd=project_path)


def git_branch_delete(project_path: str, name: str) -> dict:
    return _run_git_lines(["branch", "-D", name], cwd=project_path)


def git_branch_switch(project_path: str, name: str) -> dict:
    return _run_git_lines(["checkout", name], cwd=project_path)


def git_branch_rename(project_path: str, old_name: str, new_name: str) -> dict:
    return _run_git_lines(["branch", "-m", old_name, new_name], cwd=project_path)


def git_merge(project_path: str, from_branch: str) -> dict:
    return _run_git_lines(["merge", from_branch], cwd=project_path)


def git_stash_push(project_path: str, message: str = "") -> dict:
    args = ["stash", "push"]
    if message: args.extend(["-m", message])
    return _run_git_lines(args, cwd=project_path)


def git_stash_pop(project_path: str) -> dict:
    return _run_git_lines(["stash", "pop"], cwd=project_path)


def git_stash_list(project_path: str) -> list[dict]:
    result = []
    r = _run_git(["stash", "list", "--format=%gd|%s"], cwd=project_path)
    if r.returncode != 0: return result
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split("|", 1)
        result.append({"ref": parts[0], "message": parts[1] if len(parts) > 1 else ""})
    return result


def git_stash_drop(project_path: str, ref: str = "stash@{0}") -> dict:
    return _run_git_lines(["stash", "drop", ref], cwd=project_path)


def git_log_detailed(project_path: str, limit: int = 20, branch: str = "") -> list[dict]:
    commits = []
    args = ["log", f"--max-count={limit}", "--format=%H|%s|%an|%ai|%d", "--no-color"]
    if branch: args.insert(1, branch)
    r = _run_git(args, cwd=project_path)
    if r.returncode != 0: return commits
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split("|", 4)
        if len(parts) >= 4:
            commits.append({"hash": parts[0][:8], "full_hash": parts[0], "message": parts[1],
                           "author": parts[2], "date": parts[3], "refs": parts[4] if len(parts) > 4 else ""})
    return commits


def git_diff(project_path: str, file_path: str = "", staged: bool = False) -> str:
    args = ["diff"]
    if staged: args.append("--staged")
    if file_path: args.extend(["--", file_path])
    r = _run_git(args, cwd=project_path)
    return r.stdout if r.returncode == 0 else ""


def git_remote_list(project_path: str) -> list[dict]:
    result = []
    r = _run_git(["remote", "-v"], cwd=project_path)
    if r.returncode != 0: return result
    seen = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen:
            seen.add(parts[0])
            result.append({"name": parts[0], "url": parts[1]})
    return result


def git_remote_add(project_path: str, name: str, url: str) -> dict:
    return _run_git_lines(["remote", "add", name, url], cwd=project_path)


def git_remote_remove(project_path: str, name: str) -> dict:
    return _run_git_lines(["remote", "remove", name], cwd=project_path)


def git_reset(project_path: str, mode: str = "mixed", target: str = "HEAD") -> dict:
    return _run_git_lines(["reset", f"--{mode}", target], cwd=project_path)


def git_tag_list(project_path: str) -> list[str]:
    r = _run_git(["tag", "--sort=-creatordate"], cwd=project_path)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []


def git_tag_create(project_path: str, name: str, message: str = "") -> dict:
    args = ["tag", name]
    if message: args.extend(["-m", message])
    return _run_git_lines(args, cwd=project_path)


def git_tag_delete(project_path: str, name: str) -> dict:
    return _run_git_lines(["tag", "-d", name], cwd=project_path)


def git_custom_command(project_path: str, command: str) -> dict:
    import shlex
    return _run_git_lines(shlex.split(command), cwd=project_path)


def git_list_files(project_path: str, branch: str = "") -> list[dict]:
    """List files in the repo tree (like GitHub file view)."""
    result = []
    args = ["ls-tree", "-r", "--name-only", branch if branch else "HEAD"]
    r = _run_git(args, cwd=project_path)
    if r.returncode != 0: return result
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.rsplit("/", 1)
        dir_name = parts[0] if len(parts) > 1 else ""
        file_name = parts[-1]
        result.append({"path": line, "name": file_name, "dir": dir_name})
    return result


def git_tree(project_path: str, branch: str = "") -> list[dict]:
    """Get the full file tree (directories first, then files) without duplicates."""
    result = []
    args = ["ls-tree", "-r", "-t", branch if branch else "HEAD"]
    r = _run_git(args, cwd=project_path)
    if r.returncode != 0: return result
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split(None, 3)
        if len(parts) < 4: continue
        obj_type, path = parts[1], parts[3]
        name = path.rsplit("/", 1)[-1]
        if obj_type == "tree":
            result.append({"type": "dir", "path": path, "name": name})
        else:
            result.append({"type": "file", "path": path, "name": name})
    return result


def git_read_file(project_path: str, file_path: str, branch: str = "") -> Optional[str]:
    """Read a file from git at a given branch."""
    args = ["show", f"{branch if branch else 'HEAD'}:{file_path}"]
    r = _run_git(args, cwd=project_path)
    return r.stdout if r.returncode == 0 else None


def git_log_graph(project_path: str, limit: int = 50, all_branches: bool = True) -> list[dict]:
    """Get commit log with topological branch lanes for graphical visualization.

    Returns list of dicts:
      { "hash": str, "full_hash": str, "message": str, "author": str, "date": str,
        "refs": str, "lane": int, "parent_lanes": list[int], "active_lanes": list[int] }
    Every item corresponds to an actual commit without empty/blank phantom rows.
    """
    result = []
    args = ["log", f"--max-count={limit}", "--topo-order", "--format=%H|%P|%s|%an|%ai|%d"]
    if all_branches:
        args.insert(1, "--all")
    r = _run_git(args, cwd=project_path)
    if r.returncode != 0:
        return result

    commits = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 5)
        if len(parts) >= 5:
            full_hash = parts[0]
            parents = parts[1].split() if parts[1] else []
            commits.append({
                "hash": full_hash[:8],
                "full_hash": full_hash,
                "parents": parents,
                "message": parts[2],
                "author": parts[3],
                "date": parts[4],
                "refs": parts[5] if len(parts) > 5 else "",
                "graph": "*",
            })

    # Lane assignment algorithm
    lanes = []  # lanes[i] = full_hash of commit expected in this lane
    for c in commits:
        h = c["full_hash"]
        if h in lanes:
            lane = lanes.index(h)
        else:
            try:
                lane = lanes.index(None)
                lanes[lane] = h
            except ValueError:
                lane = len(lanes)
                lanes.append(h)
        c["lane"] = lane

        # Connect to parents
        parent_lanes = []
        c_parents = c["parents"]
        if c_parents:
            p0 = c_parents[0]
            lanes[lane] = p0
            parent_lanes.append(lane)
            for p in c_parents[1:]:
                if p in lanes:
                    parent_lanes.append(lanes.index(p))
                else:
                    try:
                        p_lane = lanes.index(None)
                        lanes[p_lane] = p
                    except ValueError:
                        p_lane = len(lanes)
                        lanes.append(p)
                    parent_lanes.append(p_lane)
        else:
            lanes[lane] = None

        c["parent_lanes"] = parent_lanes
        c["active_lanes"] = [i for i, x in enumerate(lanes) if x is not None and i != lane]

    return commits


def git_archive_zip(project_path: str, ref: str, output_path: str) -> dict:
    """Archive repository at a given ref (commit/branch/tag) into a .zip file."""
    ref_target = ref if ref and ref.strip() else "HEAD"
    r = _run_git(["archive", "--format=zip", f"--output={output_path}", ref_target], cwd=project_path)
    if r.returncode == 0:
        return {"success": True, "path": output_path}
    return {"success": False, "error": r.stderr.strip() or "Archive failed"}


def git_diff_parsed(project_path: str, file_path: str = "", staged: bool = False, commit_hash: str = "") -> list[dict]:
    """Return parsed diff with line numbers and change type (add/del/ctx/hunk/file)."""
    import re
    if commit_hash:
        args = ["show", "--format=", commit_hash]
        if file_path:
            args.extend(["--", file_path])
    else:
        args = ["diff", "-U3"]
        if staged:
            args.append("--staged")
        if file_path:
            args.extend(["--", file_path])

    r = _run_git(args, cwd=project_path)
    if r.returncode != 0 or not r.stdout:
        return []

    lines = []
    old_no = 0
    new_no = 0
    hunk_re = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")

    for raw_line in r.stdout.splitlines():
        if raw_line.startswith("diff --git") or raw_line.startswith("index "):
            lines.append({"type": "header", "old_lineno": None, "new_lineno": None, "text": raw_line})
            continue
        if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
            lines.append({"type": "file", "old_lineno": None, "new_lineno": None, "text": raw_line})
            continue

        m = hunk_re.match(raw_line)
        if m:
            old_no = int(m.group(1))
            new_no = int(m.group(2))
            lines.append({"type": "hunk", "old_lineno": None, "new_lineno": None, "text": raw_line})
            continue

        if raw_line.startswith("+"):
            lines.append({"type": "add", "old_lineno": None, "new_lineno": new_no, "text": raw_line[1:]})
            new_no += 1
        elif raw_line.startswith("-"):
            lines.append({"type": "del", "old_lineno": old_no, "new_lineno": None, "text": raw_line[1:]})
            old_no += 1
        else:
            text = raw_line[1:] if raw_line.startswith(" ") else raw_line
            lines.append({"type": "ctx", "old_lineno": old_no, "new_lineno": new_no, "text": text})
            old_no += 1
            new_no += 1

    return lines


def git_resolve_conflict(project_path: str, file_path: str, choice: str = "ours") -> dict:
    """Resolve merge conflict on a file by checking out ours or theirs and staging it."""
    if not file_path:
        return {"success": False, "error": "Thiếu đường dẫn file"}
    if choice in ("ours", "--ours"):
        r = _run_git(["checkout", "--ours", "--", file_path], cwd=project_path)
    elif choice in ("theirs", "--theirs"):
        r = _run_git(["checkout", "--theirs", "--", file_path], cwd=project_path)
    elif choice == "mark_resolved":
        r = _run_git(["add", "--", file_path], cwd=project_path)
        return {"success": r.returncode == 0, "error": r.stderr.strip() if r.returncode != 0 else ""}
    else:
        return {"success": False, "error": f"Lựa chọn không hợp lệ: {choice}"}

    if r.returncode != 0:
        return {"success": False, "error": r.stderr.strip() or "Checkout conflict file failed"}

    r_add = _run_git(["add", "--", file_path], cwd=project_path)
    return {"success": r_add.returncode == 0, "error": r_add.stderr.strip() if r_add.returncode != 0 else ""}


def git_get_author(project_path: Optional[str] = None) -> dict:
    """Get current git user.name and user.email (global, local, and effective)."""
    r_g_name = _run_git(["config", "--global", "user.name"])
    r_g_email = _run_git(["config", "--global", "user.email"])
    global_name = r_g_name.stdout.strip() if r_g_name.returncode == 0 else ""
    global_email = r_g_email.stdout.strip() if r_g_email.returncode == 0 else ""

    local_name = ""
    local_email = ""
    if project_path and is_git_repo(project_path):
        r_l_name = _run_git(["config", "--local", "user.name"], cwd=project_path)
        r_l_email = _run_git(["config", "--local", "user.email"], cwd=project_path)
        if r_l_name.returncode == 0:
            local_name = r_l_name.stdout.strip()
        if r_l_email.returncode == 0:
            local_email = r_l_email.stdout.strip()

    effective_name = local_name if local_name else global_name
    effective_email = local_email if local_email else global_email

    return {
        "name": effective_name,
        "email": effective_email,
        "global_name": global_name,
        "global_email": global_email,
        "local_name": local_name,
        "local_email": local_email,
        "is_configured": bool(effective_name and effective_email),
    }


def git_set_author(name: str, email: str, scope: str = "global", project_path: Optional[str] = None) -> dict:
    """Set git user.name and user.email (scope: 'global' or 'local')."""
    name = name.strip()
    email = email.strip()
    if not name or not email:
        return {"success": False, "error": "Name and email cannot be empty"}

    if scope == "local":
        if not project_path or not is_git_repo(project_path):
            return {"success": False, "error": "Invalid project path or not a Git repository"}
        r1 = _run_git(["config", "--local", "user.name", name], cwd=project_path)
        r2 = _run_git(["config", "--local", "user.email", email], cwd=project_path)
    else:
        r1 = _run_git(["config", "--global", "user.name", name])
        r2 = _run_git(["config", "--global", "user.email", email])

    success = (r1.returncode == 0 and r2.returncode == 0)
    err = (r1.stderr or r2.stderr).strip() if not success else ""
    return {"success": success, "error": err}


def git_get_suggested_authors(project_paths: Optional[list[str]] = None) -> list[dict]:
    """Extract distinct authors from commit history of projects."""
    suggestions = []
    seen = set()

    # Always check global first
    author_info = git_get_author()
    if author_info.get("global_name") and author_info.get("global_email"):
        key = (author_info["global_name"].lower(), author_info["global_email"].lower())
        seen.add(key)
        suggestions.append({"name": author_info["global_name"], "email": author_info["global_email"]})

    paths = project_paths or []
    for p in paths:
        if not p or not is_git_repo(p):
            continue
        r = _run_git(["log", "-n", "15", "--format=%an|%ae"], cwd=p)
        if r.returncode != 0 or not r.stdout:
            continue
        for line in r.stdout.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            aname, aemail = parts[0].strip(), parts[1].strip()
            if aname and aemail and "@" in aemail:
                key = (aname.lower(), aemail.lower())
                if key not in seen:
                    seen.add(key)
                    suggestions.append({"name": aname, "email": aemail})

    return suggestions

