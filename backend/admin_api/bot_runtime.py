import datetime
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


DEFAULT_ALPHA_MODULE = "alpha.main"
DEFAULT_MM_MODULE = "market_maker.main"


def infer_strategy_module(bot_name: str, explicit_module: Optional[str] = None) -> str:
    if explicit_module:
        return explicit_module

    lower_name = (bot_name or "").lower()
    if "maker" in lower_name or lower_name.startswith("mm"):
        return DEFAULT_MM_MODULE
    return DEFAULT_ALPHA_MODULE


@dataclass
class ManagedBotProcess:
    run_id: str
    bot_id: str
    strategy_module: str
    process: subprocess.Popen
    log_file_path: str
    started_at: datetime.datetime
    log_file_handle: object


class LiveBotProcessRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._processes_by_run: Dict[str, Dict[str, ManagedBotProcess]] = {}

    def _resolve_default_working_dir(self) -> Path:
        current_file = Path(__file__).resolve()
        candidates = [Path("/bots"), Path.cwd() / "bots"]
        candidates.extend(parent / "bots" for parent in current_file.parents)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise RuntimeError(
            "Unable to locate bots working directory. "
            "Set BOT_WORKING_DIR explicitly."
        )

    def _get_or_create_run_map(self, run_id: str) -> Dict[str, ManagedBotProcess]:
        return self._processes_by_run.setdefault(run_id, {})

    def get(self, run_id: str, bot_id: str) -> Optional[ManagedBotProcess]:
        with self._lock:
            return self._processes_by_run.get(run_id, {}).get(bot_id)

    def list_run(self, run_id: str) -> Dict[str, ManagedBotProcess]:
        with self._lock:
            return dict(self._processes_by_run.get(run_id, {}))

    def active_run_count(self) -> int:
        with self._lock:
            return len(self._processes_by_run)

    def active_bot_count(self) -> int:
        with self._lock:
            return sum(len(run_map) for run_map in self._processes_by_run.values())

    def start_bot(
        self,
        run_id: str,
        bot_id: str,
        bot_name: str,
        api_key: str,
        strategy_module: str,
        exchange_ws_url: str,
        replay_mode: bool = False,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> ManagedBotProcess:
        with self._lock:
            run_map = self._get_or_create_run_map(run_id)
            existing = run_map.get(bot_id)
            if existing and existing.process.poll() is None:
                return existing

            try:
                python_exec = os.getenv("BOT_PYTHON_EXECUTABLE", os.sys.executable)

                working_dir_env = os.getenv("BOT_WORKING_DIR")
                if working_dir_env:
                    working_dir = Path(working_dir_env)
                else:
                    working_dir = self._resolve_default_working_dir()

                if not working_dir.exists():
                    raise RuntimeError(f"Bot working directory does not exist: {working_dir}")

                log_dir = Path(os.getenv("BOT_LOG_DIR", str(Path(os.getenv("DB_DIR", "./")) / "bot_logs")))
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = log_dir / f"run_{run_id}_bot_{bot_id}.log"

                env = os.environ.copy()
                env["BOT_API_KEY"] = api_key
                env["EXCHANGE_WS_URL"] = exchange_ws_url
                env["BOT_ID"] = bot_id
                env["BOT_NAME"] = bot_name
                env["BOT_RUN_ID"] = run_id
                env["BOT_RUN_MODE"] = "replay" if replay_mode else "live"
                if extra_env:
                    for key, value in extra_env.items():
                        if value is not None:
                            env[str(key)] = str(value)

                log_file_handle = open(log_file_path, "a", encoding="utf-8")
                process = subprocess.Popen(
                    [python_exec, "-m", strategy_module],
                    cwd=str(working_dir),
                    env=env,
                    stdout=log_file_handle,
                    stderr=subprocess.STDOUT,
                )

                managed = ManagedBotProcess(
                    run_id=run_id,
                    bot_id=bot_id,
                    strategy_module=strategy_module,
                    process=process,
                    log_file_path=str(log_file_path),
                    started_at=datetime.datetime.now(datetime.timezone.utc),
                    log_file_handle=log_file_handle,
                )
                run_map[bot_id] = managed
                return managed
            except Exception:
                if not run_map:
                    self._processes_by_run.pop(run_id, None)
                raise

    def stop_bot(self, run_id: str, bot_id: str, grace_seconds: float = 8.0) -> Optional[int]:
        with self._lock:
            run_map = self._processes_by_run.get(run_id)
            if not run_map:
                return None

            managed = run_map.get(bot_id)
            if not managed:
                return None

            process = managed.process
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=grace_seconds)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=grace_seconds)
                return process.returncode
            finally:
                try:
                    managed.log_file_handle.close()
                except Exception:
                    pass
                run_map.pop(bot_id, None)
                if not run_map:
                    self._processes_by_run.pop(run_id, None)

    def stop_run(self, run_id: str) -> Dict[str, Optional[int]]:
        stopped: Dict[str, Optional[int]] = {}
        run_snapshot = self.list_run(run_id)
        for bot_id in run_snapshot.keys():
            stopped[bot_id] = self.stop_bot(run_id, bot_id)
        return stopped
