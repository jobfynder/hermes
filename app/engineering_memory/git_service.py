import subprocess


def run_git_command(args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def get_current_branch() -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])


def get_latest_commits(limit: int = 5) -> list[str]:
    output = run_git_command(["log", f"-{limit}", "--pretty=format:%h %s"])

    if not output:
        return []

    return output.splitlines()


def get_changed_files() -> list[str]:
    output = run_git_command(["diff", "--name-only", "HEAD~1", "HEAD"])

    if not output:
        return []

    return output.splitlines()


def get_repository_name() -> str:
    output = run_git_command(["config", "--get", "remote.origin.url"])

    if not output:
        return "unknown"

    repo = output.rstrip("/").split("/")[-1]

    return repo.replace(".git", "")