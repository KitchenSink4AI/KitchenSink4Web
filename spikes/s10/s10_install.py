"""S10 part 1: weight and install measurement.

Times and sizes, measured rather than quoted from DESIGN 4.1:
  * python -m venv (baseline cost of a fresh env)
  * pip install playwright, --no-cache-dir so the download is real
  * python -m playwright install per engine (chromium, firefox, webkit) into a
    scratch PLAYWRIGHT_BROWSERS_PATH so the user's real browser cache is never
    touched, with per-engine wall clock and on-disk size delta
Everything lands in scratch and is deleted at the end; the only artifact is
the JSON. Network times are recorded as network times, with the date, since
they are not reproducible constants.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PY = sys.executable
DEADLINE_S = 1500
T0 = time.monotonic()


def check_deadline():
    if time.monotonic() - T0 > DEADLINE_S:
        raise TimeoutError("s10_install exceeded %ds" % DEADLINE_S)


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def timed(cmd, env=None, timeout=900):
    check_deadline()
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    dt = time.perf_counter() - t0
    return dt, r


def mb(n):
    return round(n / (1024 * 1024), 1)


def main():
    scratch = tempfile.mkdtemp(prefix="ks4web_spike_s10_")
    venv_dir = os.path.join(scratch, "venv")
    browsers = os.path.join(scratch, "pw-browsers")
    result = {"date_kst": time.strftime("%Y-%m-%d %H:%M"), "python": sys.version.split()[0],
              "steps": []}
    print("scratch:", scratch)

    # 1. venv
    dt, r = timed([PY, "-X", "utf8", "-m", "venv", venv_dir])
    vpy = os.path.join(venv_dir, "Scripts", "python.exe")
    result["steps"].append({"step": "python -m venv", "seconds": round(dt, 1),
                            "rc": r.returncode})
    print("venv: %.1fs" % dt)
    size_before = dir_size(venv_dir)

    # 2. pip install playwright, real download
    dt, r = timed([vpy, "-X", "utf8", "-m", "pip", "install", "--no-cache-dir",
                   "playwright"], timeout=900)
    size_after = dir_size(venv_dir)
    ver = subprocess.run([vpy, "-c",
                          "import playwright._repo_version as v; print(v.version)"],
                         capture_output=True, text=True).stdout.strip()
    result["steps"].append({
        "step": "pip install playwright (--no-cache-dir)", "seconds": round(dt, 1),
        "rc": r.returncode, "playwright_version": ver,
        "site_packages_delta_mb": mb(size_after - size_before),
        "pip_tail": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""})
    print("pip install playwright: %.1fs, +%s MB, v%s" %
          (dt, mb(size_after - size_before), ver))

    # 3. per-engine browser install into scratch
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
    prev = 0
    for engine in ("chromium", "firefox", "webkit"):
        dt, r = timed([vpy, "-X", "utf8", "-m", "playwright", "install", engine],
                      env=env, timeout=900)
        now = dir_size(browsers)
        added = sorted(os.listdir(browsers)) if os.path.isdir(browsers) else []
        result["steps"].append({
            "step": "playwright install %s" % engine, "seconds": round(dt, 1),
            "rc": r.returncode, "disk_delta_mb": mb(now - prev),
            "cumulative_mb": mb(now), "dirs_present": added,
            "tail": (r.stdout + r.stderr).strip().splitlines()[-1]
                    if (r.stdout + r.stderr).strip() else ""})
        print("playwright install %s: %.1fs, +%s MB (cume %s MB)" %
              (engine, dt, mb(now - prev), mb(now)))
        prev = now

    result["totals"] = {"all_engines_disk_mb": mb(prev),
                        "venv_disk_mb": mb(dir_size(venv_dir))}

    # cleanup: everything was scratch
    shutil.rmtree(scratch, ignore_errors=True)
    result["scratch_removed"] = not os.path.exists(scratch)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "s10_install.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print("\ntotals:", result["totals"], " scratch removed:", result["scratch_removed"])


if __name__ == "__main__":
    main()
