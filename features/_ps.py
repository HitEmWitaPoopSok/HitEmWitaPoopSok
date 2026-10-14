"""One PowerShell seam for features. Fixed scripts only; inputs by environment."""
import asyncio
from typing import Optional

import winutil


async def run(script: str, env: Optional[dict] = None, timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *winutil.powershell_argv(script), env=winutil.with_env(**(env or {})),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        return -1, "", f"could not start PowerShell: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return -1, "", "PowerShell timed out"
    return (proc.returncode if proc.returncode is not None else -1,
            out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
